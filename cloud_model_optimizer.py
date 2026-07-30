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
created_elements_ids = HashSet[ElementId]()

# =========================================================================
# FUNÇÃO AUXILIAR: CONFIGURAR CROP, ANNOTATION E WORKSETS HIDE
# =========================================================================
def apply_strict_filters(document, view_or_template):
    if not view_or_template:
        return
    try:
        view_or_template.CropBoxActive = False
        view_or_template.CropBoxVisible = False
        view_or_template.AreAnnotationCategoriesHidden = True
        
        if document.IsWorkshared:
            worksets_collector = FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset)
            for wk in worksets_collector:
                if "(HIDE)" in wk.Name.upper():
                    view_or_template.SetWorksetVisibility(wk.Id, WorksetVisibility.Hidden)
    except: pass

# =========================================================================
# EXECUÇÃO DO PROCESSO EM TRANSAÇÃO ÚNICA
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

# --- PASSO 1: CRIAÇÃO/GARANTIA DAS VISTAS 3D E TEMPLATES ---
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

# --- PASSO 2: FILTRO CIRÚRGICO POR IDENTITY DATA (SHEET NAME / NUMBER) ---
try:
    all_views = FilteredElementCollector(doc).OfClass(View).ToElements()
    for view in all_views:
        try:
            v_id = view.Id
            
            # Se for uma das nossas duas vistas 3D ou templates protegidos, pula direto
            if v_id in created_elements_ids:
                continue
                
            # Ignorar tabelas, folhas físicas e componentes do navegador
            if view.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
                continue

            # Se for um View Template antigo, deleta
            if view.IsTemplate:
                doc.Delete(v_id)
                templates_deleted += 1
                continue

            # Varrer apenas vistas gráficas de projeto
            if view.ViewType in [ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation, ViewType.Section, ViewType.Detail, ViewType.ThreeD, ViewType.EngineeringPlan]:
                
                # Tenta buscar os parâmetros do Identity Data
                p_num = view.LookupParameter("Sheet Number")
                p_name = view.LookupParameter("Sheet Name")
                
                s_num = p_num.AsString() if p_num else None
                s_name = p_name.AsString() if p_name else None
                
                # Regra de Conformidade: Se tiver número E nome válidos, está em conformidade (NÃO DELETA)
                has_conformity = False
                if s_num and s_num != "" and s_num != "---" and s_num != "-":
                    if s_name and s_name != "" and s_name != "---" and s_name != "-":
                        has_conformity = True
                
                # Se NÃO tiver conformidade com os parâmetros preenchidos, passa o rodo
                if not has_conformity:
                    if view.CanBeDeleted():
                        doc.Delete(v_id)
                        views_deleted += 1
        except: pass
except: pass

# --- PASSO 3: DELEÇÃO DE GRUPOS DO BROWSER ---
try:
    group_ids = FilteredElementCollector(doc).OfClass(GroupType).ToElementIds()
    for g_id in group_ids:
        try:
            doc.Delete(g_id)
            groups_deleted += 1
        except: pass
except: pass

# --- PASSO 4: UNLOAD RVT E DELEÇÃO DE OUTROS LINKS (IFC, CAD, NAVIS) ---
try:
    rvt_links = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements()
    for link in rvt_links:
        try:
            l_name = link.Name.lower()
            if l_name.endswith(".rvt") and not link.IsNestedLink:
                if link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                    link.Unload(None)
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

try:
    pt_clouds = FilteredElementCollector(doc).OfClass(PointCloudType).ToElementIds()
    for pt_id in pt_clouds:
        try:
            doc.Delete(pt_id)
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
# RETORNO DIRETO DE TEXTO (ZERO RISCO DE SYNTAX ERROR)
# =========================================================================
OUT = "Sucesso! Vistas apagadas: " + str(views_deleted) + " | Purge total: " + str(total_purged)
