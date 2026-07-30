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
    # Coleta o tipo de família 3D padrão do projeto
    view_3d_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_family_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), None)
    
    created_elements_ids = HashSet[ElementId]()
    final_3d_views = {}

    for name in TARGET_NAMES:
        # Tenta localizar a vista 3D existente
        view_3d = next((v for v in FilteredElementCollector(doc).OfClass(View3D).ToElements() if v.Name.upper() == name), None)
        
        # Se não existir a vista 3D, cria do zero
        if not view_3d and view_3d_family_type:
            view_3d = View3D.CreateIsometric(doc, view_3d_family_type.Id)
            view_3d.Name = name
            
        final_3d_views[name] = view_3d
        created_elements_ids.Add(view_3d.Id)
        
        # Tenta localizar o View Template correspondente com o mesmo nome
        all_templates = [v for v in FilteredElementCollector(doc).OfClass(View).ToElements() if v.IsTemplate]
        template = next((t for t in all_templates if t.Name.upper() == name), None)
        
        # Se não existir o View Template, cria a partir da própria vista 3D
        if not template and view_3d:
            template = view_3d.CreateViewTemplate()
            template.Name = name
            
        created_elements_ids.Add(template.Id)
        
        # Vincula o View Template criado/encontrado à sua respectiva Vista 3D
        if view_3d and template:
            view_3d.ViewTemplateId = template.Id
            
        # Aplica os filtros pesados (Crop falso, Annotations ocultas, Worksets HIDE ocultos)
        apply_strict_filters(doc, view_3d)
        apply_strict_filters(doc, template)

    # ---------------------------------------------------------------------
    # PASSO 3: VARREDURA E DELEÇÃO AGRESSIVA DE VISTAS 2D FORA DE FOLHAS E REDUNDÂNCIAS
    # ---------------------------------------------------------------------
    all_views = FilteredElementCollector(doc).OfClass(View).ToElements()
    
    for view in all_views:
        v_id = view.Id
        
        # Protege as vistas e templates que acabamos de criar ou mapear
        if v_id in created_elements_ids:
            continue
            
        # Ignorar tabelas, folhas físicas e componentes do navegador do Revit
        if view.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
            continue

        # Se for um View Template antigo/inútil, passa o rodo
        if view.IsTemplate:
            try:
                doc.Delete(v_id)
                templates_deleted += 1
            except: pass
            continue

        # Se for qualquer tipo de vista (2D ou 3D) que NÃO está nas folhas mapeadas
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
    # PASSO 5: UNLOAD E LIMPEZA DE EXTERNAL LINKS (CAD, IFC, DWG)
    # ---------------------------------------------------------------------
    # Unload de arquivos .rvt
    rvt_links = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements()
    for link in rvt_links:
        if not link.IsNestedLink:
            try:
                if link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                    link.Unload(None)
                    rvt_unloaded += 1
                elif link.GetLinkedFileStatus() == LinkedFileStatus.Unloaded:
                    rvt_unloaded += 1
            except: pass

    # Eliminação total de instâncias importadas/vinculadas (CAD/DWG/IFC)
    import_instances = FilteredElementCollector(doc).OfClass(ImportInstance).ToElementIds()
    for inst_id in import_instances:
        try:
            doc.Delete(inst_id)
            links_removed += 1
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

except Exception as main_err:
    pass

# Executa o encerramento do Bloco A para iniciar o Purge do banco de dados
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
    "• Vínculos rígidos apagados do modelo (DWG/CAD/IFC): {}".format(links_removed),
    "• Elementos órfãos eliminados via Deep Purge: {}".format(total_purged),
    "• Ciclos de otimização de banco de dados executados: {}".format(loop_safety),
    "-"*60,
    "• CRIAÇÃO E STATUS DAS ENTREGAS:",
