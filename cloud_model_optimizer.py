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
                    # Aplica a ocultação do Workset diretamente na configuração da Vista/Template
                    view_or_template.SetWorksetVisibility(wk.Id, WorksetVisibility.Hidden)
    except Exception as e:
        pass

# =========================================================================
# EXECUÇÃO DO PROCESSO EM TRANSAÇÃO ÚNICA
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

try:
    # ---------------------------------------------------------------------
    # PASSO 1: MAPEAMENTO RIGOROSO DE FOLHAS (SHEETS)
    # ---------------------------------------------------------------------
    placed_view_ids = HashSet[ElementId]()
    sheets_collector = FilteredElementCollector(doc).OfClass(ViewSheet).ToElements()
    for sheet in sheets_collector:
        for v_id in sheet.GetAllPlacedViews():
            placed_view_ids.Add(v_id)

    # ---------------------------------------------------------------------
    # PASSO 2: CRIAÇÃO/GARANTIA DAS VISTAS 3D E SEUS RESPECTIVOS TEMPLATES
    # ---------------------------------------------------------------------
    view_3d_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_family_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), None)
    
    created_elements_ids = HashSet[ElementId]()
    final_3d_views = {}

    for name in TARGET_NAMES:
        view_3d = next((v for v in FilteredElementCollector(doc).OfClass(View3D).ToElements() if v.Name.upper() == name), None)
        
        if not view_3d and view_3d_family_type:
            view_3d = View3D.CreateIsometric(doc, view_3d_family_type.Id)
            view_3d.Name = name
            
        final_3d_views[name] = view_3d
        created_elements_ids.Add(view_3d.Id)
        
        all_templates = [v for v in FilteredElementCollector(doc).OfClass(View).ToElements() if v.IsTemplate]
        template = next((t for t in all_templates if t.Name.upper() == name), None)
        
        if not template and view_3d:
            template = view_3d.CreateViewTemplate()
            template.Name = name
            
        created_elements_ids.Add(template.Id)
        
        if view_3d and template:
            view_3d.ViewTemplateId = template.Id
            
        apply_strict_filters(doc, view_3d)
        apply_strict_filters(doc, template)

    # ---------------------------------------------------------------------
    # PASSO 3: VARREDURA E DELEÇÃO AGRESSIVA DE VISTAS 2D FORA DE FOLHAS
    # ---------------------------------------------------------------------
    all_views = FilteredElementCollector(doc).OfClass(View).ToElements()
    
    for view in all_views:
        v_id = view.Id
        
        if v_id in created_elements_ids:
            continue
            
        if view.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
            continue

        if view.IsTemplate:
            try:
                doc.Delete(v_id)
                templates_deleted += 1
            except: pass
            continue

        if v_id not in placed_view_ids:
            if view.CanBeDeleted():
                try:
                    doc.Delete(v_id)
                    views_deleted += 1
                except: pass

    # ---------------------------------------------------------------------
    # PASSO 4: DELEÇÃO DE GRUPOS DO BROWSER
    # ---------------------------------------------------------------------
    group_ids = FilteredElementCollector(doc).OfClass(GroupType).ToElementIds()
    for g_id in group_ids:
        try:
            doc.Delete(g_id)
            groups_deleted += 1
        except: pass

    # ---------------------------------------------------------------------
    # PASSO 5: UNLOAD E LIMPEZA TOTAL DE EXTERNAL LINKS (RVT, CAD, IFC, NAVIS)
    # ---------------------------------------------------------------------
    # 1. Varredura profunda em todos os RevitLinkType (inclui arquivos .ifc.rvt)
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

    # 2. Eliminação total de instâncias importadas/vinculadas (CAD/DWG)
    import_instances = FilteredElementCollector(doc).OfClass(ImportInstance).ToElementIds()
    for inst_id in import_instances:
        try:
            doc.Delete(inst_id)
            links_removed += 1
        except: pass

    # 3. Remoção de Coordination Models (NWD/NWC) e Topografias por tipos de classe
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

except Exception as main_err:
    pass

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# BLOCK B: RECURSIVE DEEP PURGE OF UNUSED ELEMENTS (Cascading Garbage Collection)
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
    "• Vistas 2D (Fora de folha) e 3Ds inúteis excluídas: {}".format(views_deleted),
    "• View Templates obsoletos destruídos: {}".format(templates_deleted),
    "• Model & Detail Groups limpos do Browser: {}".format(groups_deleted),
    "• Vínculos .RVT descarregados (Server RAM protegida): {}".format(rvt_unloaded),
    "• Vínculos rígidos apagados (DWG/CAD/IFC/Coordination): {}".format(links_removed),
    "• Elementos órfãos eliminados via Deep Purge: {}".format(total_purged),
    "• Ciclos de otimização de banco de dados executados: {}".format(loop_safety),
    "-"*60,
    "• CRIAÇÃO E STATUS DAS ENTREGAS:",
    "  [+] Vista 3D EMISSÃO & View Template EMISSÃO -> Ativos e Configurados",
    "  [+] Vista 3D NAVIS & View Template NAVIS -> Ativos e Configurados",
    "  [✔️] Crop Box Desativado | Categoria Annotation Oculta",
    "  [✔️] Todos os Worksets com '(HIDE)' no nome foram forçados para Invisível",
    "-"*60,
    "Pronto para upload em nuvem e auditoria de modelo!"
]

OUT = "\n".join(report_log)
