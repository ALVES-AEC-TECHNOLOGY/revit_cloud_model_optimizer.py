# -*- coding: utf-8 -*-
import sys
import clr

# Import Revit API Elements
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

# Import Dynamo Document and Transaction Services
clr.AddReference('RevitServices')
import RevitServices
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# Import System for .NET Collections
clr.AddReference('System')
import System
from System.Collections.Generic import HashSet

# INITIALIZATION
doc = DocumentManager.Instance.CurrentDBDocument

# Contadores para o relatório final
groups_deleted = 0
views_deleted = 0
templates_deleted = 0
rvt_unloaded = 0
links_removed = 0
total_purged = 0

TARGET_NAMES = ["3D EMISSÃO", "3D NAVIS"]

# =========================================================================
# FUNÇÃO AUXILIAR: CONFIGURAR VIEW TEMPLATE OU VISTA (CROP, ANNOTATION, WORKSETS)
# =========================================================================
def apply_strict_filters(document, view_or_template):
    if not view_or_template:
        return
    try:
        # 1. Desabilitar Crop Box (Ativo e Visível)
        view_or_template.CropBoxActive = False
        view_or_template.CropBoxVisible = False
        
        # 2. Ocultar Categoria de Anotações (Annotations Hidden)
        view_or_template.AreAnnotationCategoriesHidden = True
        
        # 3. Varrer e ocultar todos os Worksets que contenham "(HIDE)" no nome
        if document.IsWorkshared:
            workset_table = document.GetWorksetTable()
            worksets_collector = FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset)
            
            for wk in worksets_collector:
                if "(HIDE)" in wk.Name.upper():
                    view_or_template.SetWorksetVisibility(wk.Id, WorksetVisibility.Hidden)
    except:
        pass

# =========================================================================
# EXECUÇÃO DO PROCESSO EM TRANSAÇÃO ÚNICA (BLOCOS ISOLADOS)
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

# ---------------------------------------------------------------------
# PASSO 1: CRIAÇÃO/GARANTIA DAS VISTAS 3D E SEUS RESPECTIVOS TEMPLATES
# ---------------------------------------------------------------------
created_elements_ids = HashSet[ElementId]()
try:
    view_3d_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_family_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), None)
    
    for name in TARGET_NAMES:
        view_3d = next((v for v in FilteredElementCollector(doc).OfClass(View3D).ToElements() if v.Name.upper() == name), None)
        
        if not view_3d and view_3d_family_type:
            view_3d = View3D.CreateIsometric(doc, view_3d_family_type.Id)
            view_3d.Name = name
            
        if view_3d:
            created_elements_ids.Add(view_3d.Id)
            
            all_templates = [v for v in FilteredElementCollector(doc).OfClass(View).ToElements() if v.IsTemplate]
            template = next((t for t in all_templates if t.Name.upper() == name), None)
            
            if not template:
                template = view_3d.CreateViewTemplate()
                template.Name = name
                
            if template:
                created_elements_ids.Add(template.Id)
                view_3d.ViewTemplateId = template.Id
                apply_strict_filters(doc, template)
                
            apply_strict_filters(doc, view_3d)
except: pass

# ---------------------------------------------------------------------
# PASSO 2: VARREDURA POR STRING E CORRESPONDÊNCIA DE FOLHA (DELEÇÃO DE VISTAS)
# ---------------------------------------------------------------------
try:
    # Tipos gráficos legítimos que devem ser analisados para deleção
    valid_view_types = [
        ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation, 
        ViewType.Section, ViewType.Detail, ViewType.ThreeD, ViewType.EngineeringPlan
    ]
    
    all_views = FilteredElementCollector(doc).OfClass(View).ToElements()
    for view in all_views:
        try:
            v_id = view.Id
            
            # Se for um View Template antigo/inútil, deleta (protegendo os do Passo 1)
            if view.IsTemplate:
                if v_id not in created_elements_ids:
                    doc.Delete(v_id)
                    templates_deleted += 1
                continue

            # Analisar apenas vistas gráficas reais de projeto (2D e 3D)
            if view.ViewType in valid_view_types:
                v_name_upper = view.Name.upper()
                
                # Se for uma das duas vistas 3D protegidas, ignora imediatamente
                if v_id in created_elements_ids or any(target in v_name_upper for target in TARGET_NAMES):
                    continue
                
                # CHECAGEM CIRÚRGICA POR CORRESPONDÊNCIA DE FOLHA (NUMBER / NAME)
                # Pega os parâmetros nativos do Revit que indicam o vínculo com prancha
                param_sheet_num = view.get_Parameter(BuiltInParameter.VIEWER_SHEET_NUMBER)
                param_sheet_name = view.get_Parameter(BuiltInParameter.VIEWER_SHEET_NAME)
                
                sheet_num = param_sheet_num.AsString() if param_sheet_num else None
                sheet_name = param_sheet_name.AsString() if param_sheet_name else None
                
                # Se os parâmetros não existirem, forem nulos, vazios ou contiverem "-", a vista está fora da folha
                is_on_sheet = True
                if not sheet_num or sheet_num == "" or sheet_num == "---" or sheet_num == "-":
                    if not sheet_name or sheet_name == "" or sheet_name == "---" or sheet_name == "-":
                        is_on_sheet = False
                
                # Se for comprovado que não tem correspondência em folha, passa o rodo
                if not is_on_sheet:
                    if view.CanBeDeleted():
                        doc.Delete(v_id)
                        views_deleted += 1
        except: pass
except: pass

# ---------------------------------------------------------------------
# PASSO 3: DELEÇÃO DE GRUPOS DO BROWSER
# ---------------------------------------------------------------------
try:
    group_ids = FilteredElementCollector(doc).OfClass(GroupType).ToElementIds()
    for g_id in group_ids:
        try:
            doc.Delete(g_id)
            groups_deleted += 1
        except: pass
except: pass

# ---------------------------------------------------------------------
# PASSO 4: UNLOAD E LIMPEZA TOTAL DE EXTERNAL LINKS (RVT, CAD, IFC, NAVIS)
# ---------------------------------------------------------------------
try:
    rvt_links = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements()
    for link in rvt_links:
        try:
            l_name = link.Name.lower()
            if l_name.endswith(".rvt") and not link.IsNestedLink:
                if link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                    link.Unload(None)
                    rvt_unloaded += 1
                elif link.GetLinkedFileStatus() == LinkedFileStatus.Unloaded:
                    rvt_unloaded += 1
            elif ".ifc" in l_name:
                doc.Delete(link.Id)
                links_removed += 1
        except: pass
except: pass

try:
    import_instances = FilteredElementCollector(doc).OfClass(ImportInstance).ToElementIds()
    for inst_id in import_instances:
        try:
            doc.Delete(inst_id)
            links_removed += 1
        except: pass
except: pass

link_classes = [CADLinkType, PointCloudType]
try: link_classes.append(CoordinationModelType)
except: pass
try: link_classes.append(TopographyLinkType)
except: pass

for cls in link_classes:
    try:
        lnk_ids = FilteredElementCollector(doc).OfClass(cls).ToElementIds()
        for l_id in lnk_ids:
            try:
                doc.Delete(l_id)
                links_removed += 1
            except: pass
    except: pass

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# BLOCK B: RECURSIVE DEEP PURGE OF UNUSED ELEMENTS
# =========================================================================
loop_safety = 0
max_loops = 10 

while loop_safety < max_loops:
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        unused_ids = doc.GetUnusedElements(System.Collections.Generic.HashSet[ElementId]())
    except:
        TransactionManager.Instance.TransactionTaskDone()
        break
    
    if not unused_ids or unused_ids.Count == 0:
        TransactionManager.Instance.TransactionTaskDone()
        break 
        
    purged_this_loop = 0
    for e_id in unused_ids:
        try:
            doc.Delete(e_id)
            purged_this_loop += 1
            total_purged += 1
        except: pass
            
    TransactionManager.Instance.TransactionTaskDone()
    if purged_this_loop == 0:
        break
    loop_safety += 1

# =========================================================================
# LOG DE PERFORMANCE FINAL
# =========================================================================
report_log = [
    "🔥 ALVES AEC TECH - DEEP DELIVERY PURGE COMPLETED 🔥",
    "-"*60,
    "• Vistas 2D (Sem correspondência em folha) e 3Ds obsoletas excluídas: {}".format(views_deleted),
    "• View Templates obsoletos destruídos: {}".format(templates_deleted),
    "• Model & Detail Groups limpos do Browser: {}".format(groups_deleted),
    "• Vínculos .RVT descarregados (Server RAM protegida): {}".format(rvt_unloaded),
    "• Vínculos rígidos apagados (DWG/CAD/IFC/Coordination): {}".format(links_removed),
    "• Elementos órfãos eliminados via Deep Purge: {}".format(total_purged),
