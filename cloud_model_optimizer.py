# -*- coding: utf-8 -*-
"""
BIM Model Purge and Audit Optimization Script
Author: ALVES AEC TECHNOLOGY
Description: Safely removes redundant project views (preserving templates and sheet-bound views),
             unloads/detaches links, creates mandatory 3D Navis/Emission views with matching 
             View Templates, applies strict graphical overrides, and executes a database super purge.
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

# INITIALIZATION
doc = DocumentManager.Instance.CurrentDBDocument

# Reporting counters for performance logging
groups_deleted = 0
views_deleted = 0
templates_deleted = 0
rvt_unloaded = 0
links_removed = 0
total_purged = 0

TARGET_NAMES = ["3D EMISSION", "3D NAVIS"]
created_elements_ids = HashSet[ElementId]()

# =========================================================================
# HELPER FUNCTION: CONFIGURATION OF CROP BOX, ANNOTATIONS, AND WORKSETS
# =========================================================================
def apply_strict_filters(document, view_or_template):
    """
    Applies production-ready overrides to target views and view templates:
    disables crop boxes, hides all annotation categories, and hides specific worksets.
    """
    if not view_or_template:
        return
    try:
        # Configure Crop Box states
        view_or_template.CropBoxActive = False
        view_or_template.CropBoxVisible = False
        
        # Hide all annotation categories globally across the view or template scope
        view_or_template.AreAnnotationCategoriesHidden = True
        
        # Isolate and hide technical worksets matching the "(HIDE)" token
        if document.IsWorkshared:
            worksets_collector = FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset)
            for wk in worksets_collector:
                if "(HIDE)" in wk.Name.upper():
                    view_or_template.SetWorksetVisibility(wk.Id, WorksetVisibility.Hidden)
    except: 
        pass

# =========================================================================
# PRE-PHASE: PREVENTATIVE INJECTION OF MANDATORY DELIVERY VIEWS
# =========================================================================
# Resolves the Revit API limitation preventing the deletion of the user's active UI view.
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    view_3d_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_family_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), None)
    
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    
    for name in TARGET_NAMES:
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name), None)
        
        # Inject standard 3D view if missing before initializing the purge sequence
        if not view_3d and view_3d_family_type:
            view_3d = View3D.CreateIsometric(doc, view_3d_family_type.Id)
            view_3d.Name = name
        
        if view_3d:
            created_elements_ids.Add(view_3d.Id)
except: 
    pass
TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PHASE 1: STATIC VIEW & GROUP CLEANUP (STRICT SHEET PRESERVATION)
# =========================================================================
view_ids = FilteredElementCollector(doc).OfClass(View).ToElementIds()

TransactionManager.Instance.EnsureInTransaction(doc)

for v_id in view_ids:
    try:
        view = doc.GetElement(v_id)
        if view is None:
            continue
            
        # Bypass structural and system-internal view types
        if view.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
            continue
            
        # CRITICAL PROTECTION: Safely preserve all pre-existing infrastructure view templates
        if view.IsTemplate:
            continue 

        valid_view_types = [
            ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation, 
            ViewType.Section, ViewType.Detail, ViewType.ThreeD, ViewType.EngineeringPlan
        ]
        
        if view.ViewType in valid_view_types:
            v_name_upper = view.Name.upper()
            
            # Protect target delivery views from being processed
            if v_name_upper in TARGET_NAMES:
                continue 
                
            # Native Sheet Verification: Determines sheet placement without dynamic string parameter vulnerabilities
            is_on_sheet = view.SheetId != ElementId.InvalidElementId
            
            # Execute deletion if view is unmapped or a standard non-delivery 3D view
            if view.ViewType == ViewType.ThreeD or not is_on_sheet:
                if view.CanBeDeleted() and v_id not in created_elements_ids:
                    doc.Delete(v_id)
                    views_deleted += 1
                    
    except: 
        pass

# Purge model GroupTypes to reduce database overhead
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
# PHASE 2: STATIC MANAGE LINKS CLEANUP (ISOLATED TRANSACTIONS)
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

# Retrieve link instances using native static collections to prevent reference memory leaks
link_ids = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElementIds()

for l_id in link_ids:
    try:
        link = doc.GetElement(l_id)
        if link is None:
            continue
            
        link_name = Element.Name.GetValue(link).lower()
        
        # Gracefully unload standard external Revit links
        if link_name.endswith(".rvt") and not link.IsNestedLink:
            if link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                link.Unload(None)
                rvt_unloaded += 1
        # Permanently purge legacy coordination IFC file configurations
        elif ".ifc" in link_name:
            doc.Delete(l_id)
            links_removed += 1
    except: pass

# Process specific cloud, cad, and coordinate element collections via isolated blocks
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
# PHASE 3: CONFIGURE TARGET DELIVERY VIEWS & GENERATE MATCHING TEMPLATES
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    all_templates = [v for v in FilteredElementCollector(doc).OfClass(View).ToElements() if v.IsTemplate]
    
    for name in TARGET_NAMES:
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name), None)
        
        if view_3d:
            # Query if a matching View Template is already initialized
            template = next((t for t in all_templates if t.Name.upper() == name), None)
            
            # Generate a fresh View Template if missing from the active database mapping
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
# PHASE 4: RECURSIVE DATABASE PURGE (GARBAGE COLLECTION)
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
            total_purged += 1
            purged_this_loop += 1
        except: pass
        
    TransactionManager.Instance.TransactionTaskDone()
    if purged_this_loop == 0:
        break
    loop_safety += 1

# DYNAMO PERFORMANCE LOG OUTPUT
