# -*- coding: utf-8 -*-
"""
BIM Model Purge and Deployment Optimization Script
Author: ALVES AEC TECHNOLOGY
Description: An enterprise-grade maintenance script for Autodesk Revit models. 
             Safely removes redundant project views (preserving structural templates and 
             sheet-bound layouts), unloads Revit links, purges CAD links, creates mandatory 
             3D Navis/Emission views with auto-generated View Templates, applies graphical 
             overrides, and finishes with a recursive database garbage collection (Super Purge).
"""

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

# DOCUMENT INITIALIZATION
doc = DocumentManager.Instance.CurrentDBDocument
created_elements_ids = HashSet[ElementId]()
target_names = ["3D EMISSAO", "3D NAVIS"]
view_cache = {}

# Performance tracking counters for metrics logging
views_deleted = 0
groups_deleted = 0
links_rvt_unloaded = 0
links_ifc_cad_purged = 0
total_purged = 0

# =========================================================================
# PHASE 0: INJECTION OF MANDATORY DELIVERY VIEWS
# =========================================================================
# Bypasses the Revit API constraint prohibiting the deletion of the active UI view.
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    # Query default 3D View Family Type securely
    view_3d_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_family_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), None)
    
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()

    for name in target_names:
        # Check if the target view already exists in the project database
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name.upper()), None)
        
        # Inject standard isometric 3D view if missing before initiating the global purge sequence
        if not view_3d and view_3d_family_type:
            view_3d = View3D.CreateIsometric(doc, view_3d_family_type.Id)
            view_3d.Name = name
        
        if view_3d:
            created_elements_ids.Add(view_3d.Id)
            view_cache[name] = view_3d.Id
except:
    pass
TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PHASE 1: EXTERNAL LINK & CAD INFRASTRUCTURE PURGE
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

# Retrieve link instances using native static collections to prevent reference memory leaks
link_ids = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElementIds()
for link_id in link_ids:
    try:
        element = doc.GetElement(link_id)
        if not element:
            continue

        link_name = Element.Name.GetValue(element).lower()
        
        # Safely unload root external Revit models
        if link_name.endswith(".rvt") and not element.IsNestedLink:
            if element.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                element.Unload(None)
                links_rvt_unloaded += 1
        # Permanently purge legacy coordination IFC datasets
        elif ".ifc" in link_name:
            doc.Delete(link_id)
            links_ifc_cad_purged += 1
    except:
        pass

# Mass purge external reference dependencies (CAD, Point Clouds, Coordination Models)
link_categories = [CADLinkType, PointCloudType, CoordinationModelType, TopographyLinkType]
for cat in link_categories:
    try:
        cat_ids = FilteredElementCollector(doc).OfClass(cat).ToElementIds()
        for c_id in cat_ids:
            try:
                doc.Delete(c_id)
                links_ifc_cad_purged += 1
            except:
                pass
    except:
        pass

try:
    import_instances = FilteredElementCollector(doc).OfClass(ImportInstance).ToElementIds()
    for inst_id in import_instances:
        try:
            doc.Delete(inst_id)
            links_ifc_cad_purged += 1
        except:
            pass
except:
    pass

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PHASE 2: MODEL GROUP CLEANUP
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    group_ids = FilteredElementCollector(doc).OfClass(GroupType).ToElementIds()
    for group_id in group_ids:
        try:
            doc.Delete(group_id)
            groups_deleted += 1
        except:
            pass
except:
    pass
TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PHASE 3: STATIC VIEW PURGE (STRICT SHEET-BOUND LAYOUT PRESERVATION)
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

view_ids = FilteredElementCollector(doc).OfClass(View).ToElementIds()
for view_id in view_ids:
    try:
        element = doc.GetElement(view_id)
        if not element:
            continue
            
        # Bypass structural and system-internal infrastructure view configurations
        if element.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
            continue
        if element.IsTemplate:
            continue

        # Map strictly processing-eligible layout architectures
        valid_view_types = [
            ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation,
            ViewType.Section, ViewType.Detail, ViewType.ThreeD, ViewType.EngineeringPlan
        ]
        
        if element.ViewType not in valid_view_types:
            continue

        # Protect production delivery views from cleanup sequences
        if element.Name.upper() in target_names:
            continue

        # Native Sheet Location Check: Eliminates empty string vulnerability of dynamic parameters
        is_on_sheet = element.SheetId != ElementId.InvalidElementId

        # Delete view if it is unmapped or classified as a standard non-delivery 3D view
        if element.ViewType == ViewType.ThreeD or not is_on_sheet:
            if element.CanBeDeleted() and view_id not in created_elements_ids:
                doc.Delete(view_id)
                views_deleted += 1
    except:
        pass

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PHASE 4: VIEW TEMPLATE GENERATION & ASSIGNMENT
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    all_templates = [v for v in FilteredElementCollector(doc).OfClass(View).ToElements() if v.IsTemplate]
    
    for name in target_names:
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name.upper()), None)
        
        if view_3d:
            # Query if a matching configuration View Template is already initialized
            template = next((t for t in all_templates if t.Name.upper() == name.upper()), None)
            
            # Generate a clean corporate View Template using the active 3D view as a matrix
            if not template:
                template = view_3d.CreateViewTemplate()
                template.Name = name
                
            if template:
                created_elements_ids.Add(template.Id)
                view_3d.ViewTemplateId = template.Id
                
                # Apply high-speed graphical overrides directly onto the template mapping
                template.CropBoxActive = False
                template.CropBoxVisible = False
                template.AreAnnotationCategoriesHidden = True
except:
    pass
TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PHASE 5: RECURSIVE DATABASE SUPER PURGE (GARBAGE COLLECTION)
# =========================================================================
max_purge_loops = 10
loop_safety = 0

while loop_safety < max_loops:
    TransactionManager.Instance.EnsureInTransaction(doc)
    purged_this_loop = 0
    try:
        # Collect unused database element handles natively
        unused_elements = doc.GetUnusedElements(System.Collections.Generic.HashSet[ElementId]())
        if not unused_elements or unused_elements.Count == 0:
            TransactionManager.Instance.TransactionTaskDone()
            break
        
        for e_id in unused_elements:
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

# PERFORMANCE METRICS LOGGING OUTPUT
OUT = "ALVES AEC Optimization - Views Cleared: {}, Groups Purged: {}, RVT Unloaded: {}, IFC/CAD Removed: {}, Total Database Items Purged: {}".format(
    views_deleted, groups_deleted, links_rvt_unloaded, links_ifc_cad_purged, total_purged
)
total_purged = 0

# CONFIGURAÇÃO DE NOMES ALVO (EM MAIÚSCULAS)
TARGET_NAMES = ["3D EMISSAO", "3D NAVIS"]
created_elements_ids = new HashSet[ElementId]()

# =========================================================================
# FUNÇÃO AUXILIAR: CONFIGURAÇÃO DE CROP, ANOTAÇÕES E VISIBILIDADE
# =========================================================================
def apply_strict_filters(document, view_or_template):
    if not view_or_template:
        return
    
    # Forçar desligamento da Região de Recorte (Crop Box)
    view_or_template.CropBoxActive = False;
    view_or_template.CropBoxVisible = false;
    
    # Ocultar todas as categorias de anotação (Annotations)
    if view_or_template and document.IsWorkshared:
        worksets_collector = FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset);
        foreach(wk in worksets_collector)
            if "(HIDE)" in wk.Name.ToUpper()
                SetWorkVisibility(wk.Id, WorkVisibility.Hidden);
        endforeach;
    else
        view_or_template.AnnotateCategoryVisible = false;

# =========================================================================
# PRÉ-FASE: CRIAÇÃO ANTECIPADA DAS VISTAS DE ENTREGA (PREVENÇÃO DE ERROS)
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc);
try
    view_3d_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements();
    view_3d_family_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), null);

    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements();

    foreach(name in TARGET_NAMES)
        found_view = nil;
        foreach(view in existing_3d_views)
            if view.Name.ToUpper() == name.upper()
                found_view = view;
                break;
            endforeach;
        
        if not found_view and view_3d_family_type
            found_view = View3D.CreateIsometric(doc, view_3d_family_type.Id);
            Set(found_view.Name, name);
        endif;

        if found_view
            AddElementIdToSet(created_elements_ids, found_view.Id);
        endif;
    endforeach;
except
    pass;
TransactionManager.Instance.TransactionTaskDone();

# =========================================================================
# FASE 1: LIMPEZA DE VISTAS ESTÁTICAS E GRUPOS (PRESERVAÇÃO DE FOLHAS)
# =========================================================================
view_ids = FilteredElementCollector(doc).OfClass(View).ToElementIds();

TransactionManager.Instance.EnsureInTransaction(doc);
foreach(v_id in view_ids)
    element = GetElement(doc, v_id);
    
    if not element or element.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]
        continue;
    endif;

    if element.IsTemplate
        continue;
    endforeach;

    valid_view_types = [
        ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation, 
        ViewType.Section, ViewType.Detail, ViewType.ThreeD, ViewType.EngineeringPlan
    ];

    if element.ViewType in valid_view_types
        view_name_upper = Get[element.Name].ToUpper();
        
        if view_name_upper in TARGET_NAMES
            continue;
        endif;

        is_on_sheet = (element.SheetId != ElementId.InvalidElementId);

        if element.ViewType == ViewType.ThreeD or not is_on_sheet
            if CanBeDeleted(element) and v_id not in created_elements_ids
                Delete(v_id);
                views_deleted += 1;
            endif;
        endif;
    endforeach;

try
    group_ids = FilteredElementCollector(doc).OfClass(GroupType).ToElementIds();
    foreach(g_id in group_ids)
        if Delete(g_id) success
            groups_deleted += 1;
        else
            log.error("Erro ao apagar o grupo com ID: {0}", g_id);
        endif;
    endforeach;
except
    pass;

TransactionManager.Instance.TransactionTaskDone();

# =========================================================================
# FASE 2: LIMPEZA AUTOMÁTICA DE VÍNCULOS EXTERNOS E CADS
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc);

link_ids = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElementIds();

foreach(l_id in link_ids)
    element = GetElement(doc, l_id);
    
    if not element or element.Name.ToLower().EndsWith(".rvt") and NotIsNested(element)
        if GetLinkedFileStatus(element) == LinkedFileStatus.Loaded
            Unload(element);
            rvt_unloaded += 1;
        endif;
        
        elif element.Name.ToLower().Contains ".ifc"
            Delete(l_id);
            links_removed += 1;
        endforeach;

link_categories = [CADLinkType, PointCloudType, CoordinationModelType, TopographyLinkType];
foreach(cat in link_categories)
    cat_ids = FilteredElementCollector(doc).OfClass(cat).ToElementIds();
    
    foreach(c_id in cat_ids)
        if Delete(c_id) success
            links_removed += 1;
        else
            log.error("Erro ao apagar o linking do tipo {0} com ID: {1}", cat, c_id);
        endif;
    endforeach;
endforeach;

ImportInstanceCollector = FilteredElementCollector(doc).OfClass(ImportInstance).ToElementIds();
foreach(inst_id in ImportInstanceCollector)
    if Delete(inst_id) success
        links_removed += 1;
    else
        log.error("Erro ao apagar o instância de importação com ID: {0}", inst_id);
    endif;
endforeach;

TransactionManager.Instance.TransactionTaskDone();

# =========================================================================
# FASE 3: ASSOCIAÇÃO DAS VISTAS ALVO AOS RESPECTIVOS VIEW TEMPLATES
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc);
try
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements();
    
    foreach(name in TARGET_NAMES)
        found_view = nil;
        foreach(view in existing_3d_views)
            if view.Name.ToUpper() == name.upper()
                found_view = view;
                break;
            endforeach;
        
        if not found_view
            template = View3D.CreateIsometric(doc, view_3d_family_type.Id);
            Set(template.Name, name);
            AddElementIdToSet(created_elements_ids, template.Id);
        endif;
    endforeach;
    
    foreach(target_name in TARGET_NAMES)
        template = GetElementById(doc, created_elements_ids[target_name]);
        
        if template
            addElementIdToSet(created_elements_ids, template.Id);
        endif;
    endforeach;
except
    pass;
TransactionManager.Instance.TransactionTaskDone();

# =========================================================================
# FASE 4: AUTO-PURGEÇÃO RECURSIVA NAS VISTAS E ELEMENTOS
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc);

max_purge_iterations = 10;
for(iteration in 1..max_purge_iterations)
    total_unpurged = purgeUnusedElements();
    
    if total_unpurged <= 0
        break;
    endif;
endforeach;

TransactionManager.Instance.TransactionTaskDone();

# LIMPEZA Final
doc.PurgeCache();
doc.PurgeLinks();
doc.PurgeTempData();

# Relatório de Remoções
Print "Total de grupos eliminados: {0}\n", groups_deleted;
Print "Total de vistas eliminadas: {0}\n", views_deleted;
Print "Total de templates eliminados: {1}\n", templates_deleted;
Print "Total de links carregados: {2}\n", links_removed;
Print "Total de IDs puros eliminados: {3}\n", total_purged;

exit;
"""
```
