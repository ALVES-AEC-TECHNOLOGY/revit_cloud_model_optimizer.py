```python
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
import Autodesk

def delete_unused_views(doc):
    collector = FilteredElementCollector(doc)
    views = [e for e in collector.OfClass(View) if not e.IsTemplate and not e.IsPrintingView]

    used_views = set()
    sheets = FilteredElementCollector(doc).OfClass(Sheet).ToElements()

    for sheet in sheets:
        used_views.update(sheet.GetAllPlacedViews())

    for view in views:
        if view.Id not in used_views:
            doc.Delete(view.Id)

def delete_groups(doc):
    collector = FilteredElementCollector(doc)
    groups = [e for e in collector.OfClass(Group)]

    for group in groups:
        doc.Delete(group.Id)

def unload_links(doc):
    collector = FilteredElementCollector(doc).OfClass(RevitLinkType)
    link_types = collector.ToElements()

    for link_type in link_types:
        if not isinstance(link_type, RevitLinkInstance):
            continue

        link_instance = doc.GetElement(link_type.GetTargetId())
        doc.Delete(link_instance.Id)

def super_purge(doc):
    uidoc = Autodesk.Revit.UI.DocumentManager.Instance.CurrentUIDocument
    cmd_data = CommandData()
    command = SuperPurgeCommand(cmd_data)
    command.Execute()

def main():
    doc = __revit__.ActiveUIDocument.Document
    delete_unused_views(doc)
    delete_groups(doc)
    unload_links(doc)
    super_purge(doc)

if __name__ == '__main__':
    main()
```
    for e_id in unused_ids:
        try:
            doc.Delete(e_id)
            purged_this_loop += 1
            total_purged_count += 1
        except:
            pass
            
    TransactionManager.Instance.TransactionTaskDone()
    if purged_this_loop == 0: 
        break
    purge_cycles_count += 1

# =========================================================================
# OUTPUT REPORT
# =========================================================================
final_report = [
    "🔥 CLEANING COMPLETED 🔥",
    "-" * 45,
    "• Group Types deleted from Browser: {}".format(deleted_groups_count),
    "• Total redundant items Purged: {}".format(total_purged_count),
    "• Purge loop execution cycles: {}".format(purge_cycles_count),
    "-" * 45
]

OUT = "\n".join(final_report)
total_purged = 0

# CONFIGURAÇÃO DE NOMES ALVO (EM MAIÚSCULAS)
TARGET_NAMES = ["3D EMISSAO", "3D NAVIS"]
created_elements_ids = HashSet[ElementId]()

# =========================================================================
# FUNÇÃO AUXILIAR: CONFIGURAÇÃO DE CROP, ANOTAÇÕES E VISIBILIDADE
# =========================================================================
def apply_strict_filters(document, view_or_template):
    if not view_or_template:
        return
    try:
        # Forçar desligamento da Região de Recorte (Crop Box)
        view_or_template.CropBoxActive = False
        view_or_template.CropBoxVisible = False
        
        # Ocultar todas as categorias de anotação (Annotations)
        view_or_template.AreAnnotationCategoriesHidden = True
        
        # Ocultar automaticamente Worksets técnicos com o token "(HIDE)" no nome
        if document.IsWorkshared:
            worksets_collector = FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset)
            for wk in worksets_collector:
                if "(HIDE)" in wk.Name.upper():
                    view_or_template.SetWorksetVisibility(wk.Id, WorksetVisibility.Hidden)
    except: 
        pass

# =========================================================================
# PRÉ-FASE: CRIAÇÃO ANTECIPADA DAS VISTAS DE ENTREGA (PREVENÇÃO DE ERROS)
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    view_3d_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_family_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), None)
    
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    
    for name in TARGET_NAMES:
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name), None)
        
        if not view_3d and view_3d_family_type:
            view_3d = View3D.CreateIsometric(doc, view_3d_family_type.Id)
            view_3d.Name = name
        
        if view_3d:
            created_elements_ids.Add(view_3d.Id)
except: 
    pass
TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# FASE 1: LIMPEZA DE VISTAS ESTÁTICAS E GRUPOS (PRESERVAÇÃO DE FOLHAS)
# =========================================================================
view_ids = FilteredElementCollector(doc).OfClass(View).ToElementIds()

TransactionManager.Instance.EnsureInTransaction(doc)

for v_id in view_ids:
    try:
        view = doc.GetElement(v_id)
        if view is None:
            continue
            
        if view.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
            continue
            
        if view.IsTemplate:
            continue 

        valid_view_types = [
            ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation, 
            ViewType.Section, ViewType.Detail, ViewType.ThreeD, ViewType.EngineeringPlan
        ]
        
        if view.ViewType in valid_view_types:
            v_name_upper = view.Name.upper()
            
            if v_name_upper in TARGET_NAMES:
                continue 
                
            is_on_sheet = view.SheetId != ElementId.InvalidElementId
            
            if view.ViewType == ViewType.ThreeD or not is_on_sheet:
                if view.CanBeDeleted() and v_id not in created_elements_ids:
                    doc.Delete(v_id)
                    views_deleted += 1
                    
    except: 
        pass

try:
    group_ids = FilteredElementCollector(doc).OfClass(GroupType).ToElementIds()
    for g_id in group_ids:
        try:
            doc.Delete(g_id)
            groups_deleted += 1
        except: pass
except: pass

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# FASE 2: LIMPEZA AUTOMÁTICA DE VÍNCULOS EXTERNOS E CADS
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

link_ids = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElementIds()

for l_id in link_ids:
    try:
        link = doc.GetElement(l_id)
        if link is None:
            continue
            
        link_name = Element.Name.GetValue(link).lower()
        
        if link_name.endswith(".rvt") and not link.IsNestedLink:
            if link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                link.Unload(None)
                rvt_unloaded += 1
        elif ".ifc" in link_name:
            doc.Delete(l_id)
            links_removed += 1
    except: pass

link_categories = [CADLinkType, PointCloudType, CoordinationModelType, TopographyLinkType]
for cat in link_categories:
    try:
        cat_ids = FilteredElementCollector(doc).OfClass(cat).ToElementIds()
        for c_id in cat_ids:
            try:
                doc.Delete(c_id)
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

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# FASE 3: ASSOCIAÇÃO DAS VISTAS ALVO AOS RESPECTIVOS VIEW TEMPLATES
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    all_templates = [v for v in FilteredElementCollector(doc).OfClass(View).ToElements() if v.IsTemplate]
    
    for name in TARGET_NAMES:
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name), None)
        
        if view_3d:
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
TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# FASE 4: SUPER PURGE RECURSIVO (COLETA DE LIXO DA BASE DE DADOS BIM)
# =========================================================================
loop_safety = 0
max_loops = 10 

while loop_safety < max_loops:
    TransactionManager.Instance.EnsureInTransaction(doc)
    purged_this_loop = 0
    try:
        unused_ids = doc.GetUnusedElements(System.Collections.Generic.HashSet[ElementId]())
        if not unused_ids or unused_ids.Count == 0:
            TransactionManager.Instance.TransactionTaskDone()
            break
            
        for e_id in unused_ids:
            try:
                doc.Delete(e_id)
                total_purged += 1
                purged_this_loop += 1
            except: 
                pass
    except:
        TransactionManager.Instance.TransactionTaskDone()
        break
        
    TransactionManager.Instance.TransactionTaskDone()
    if purged_this_loop == 0:
        break
    loop_safety += 1

# SAÍDA DE LOG DE PERFORMANCE PARA O NODE DO DYNAMO
OUT = "Otimizacao ALVES AEC - Vistas Limpas: {}, Grupos Removidos: {}, Vinculos Removidos: {}, Itens Purgados: {}".format(views_deleted, groups_deleted, links_removed, total_purged)
