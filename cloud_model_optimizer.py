import sys
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

# .NET Support required for CPython3
clr.AddReference('System')
import System
from System.Collections.Generic import HashSet

clr.AddReference('RevitServices')
import RevitServices
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# Document Initialization
doc = DocumentManager.Instance.CurrentDBDocument

deleted_groups_count = 0
deleted_views_count = 0
unloaded_rvt_count = 0
removed_links_count = 0
total_purged_count = 0
purge_cycles_count = 0

# =========================================================================
# BLOCK 1: DELETIONS AND GENERAL MODEL CLEANING
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

# STEP 1: Delete Model & Detail Groups from the Project Browser
group_ids = list(FilteredElementCollector(doc).OfClass(GroupType).ToElementIds())
for g_id in group_ids:
    try:
        doc.Delete(g_id)
        deleted_groups_count += 1
    except:
        pass

# STEP 2: Clean Unplaced Views Using a Temporary Internal Schedule
views_to_delete_from_schedule = set()
temp_schedule = None

try:
    # 2.1 Create a temporary View Schedule in the model
    temp_schedule = ViewSchedule.CreateSchedule(doc, ElementId(BuiltInCategory.OST_Views))
    temp_schedule.Name = "### TEMP_SCHEDULE_AUTOMATIC_CLEANUP ###"
    
    # 2.2 Add the "Sheet Number" field to the schedule definition
    definition = temp_schedule.Definition
    sheet_num_field = None
    
    for sched_field in definition.GetSchedulableFields():
        if sched_field.ParameterId == ElementId(BuiltInParameter.VIEWPORT_SHEET_NUMBER):
            sheet_num_field = definition.AddField(sched_field)
            break
            
    # 2.3 Apply the schedule filter: "Sheet Number" EQUALS "" (Empty / Not on sheet)
    if sheet_num_field:
        schedule_filter = ScheduleFilter(sheet_num_field.FieldId, ScheduleFilterType.Equal, "")
        definition.AddFilter(schedule_filter)
        
    # 2.4 Force Revit to regenerate database and collect resulting elements from the schedule
    doc.Regenerate()
    schedule_collector = FilteredElementCollector(doc, temp_schedule.Id).ToElementIds()
    
    for v_id in schedule_collector:
        views_to_delete_from_schedule.add(v_id)
        
except:
    pass

# 2.5 Execute the deletion loop on the collected views
view_ids = list(FilteredElementCollector(doc).OfClass(View).ToElementIds())
for v_id in view_ids:
    try:
        view = doc.GetElement(v_id)
        if view is None:
            continue
            
        # PROTECTION: If it is a View Template, SKIP (Never delete)
        if view.IsTemplate:
            continue
            
        # Ignore schedules, sheets, and critical internal system views
        v_type = view.ViewType
        if v_type in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
            continue

        # ENCODING FIX: Convert view name to clean ASCII string, stripping out special characters
        raw_name = str(view.Name).upper()
        v_name = raw_name.encode('ascii', 'ignore').decode('ascii')

        # EXCLUSIVE RULE FOR 3D VIEWS (Keep only the required manual emissions views)
        if v_type == ViewType.ThreeD:
            if "3D EMISSAO" in v_name or "3D NAVIS" in v_name:
                continue 
            doc.Delete(v_id)
            deleted_views_count += 1
            continue

        # RULE FOR 2D VIEWS (Plans, Sections, Elevations) caught by the temporary schedule
        if v_id in views_to_delete_from_schedule:
            # Protection against views generating dependent views (Parent Views)
            dependent_ids = list(view.GetDependentViewIds())
            if len(dependent_ids) > 0:
                continue
                
            if not view.CanBeDeleted():
                continue
                
            doc.Delete(v_id)
            deleted_views_count += 1
            
    except:
        pass

# 2.6 Delete the temporary schedule to leave no traces in the Project Browser
if temp_schedule:
    try:
        doc.Delete(temp_schedule.Id)
    except:
        pass

# STEP 3: Manage Document Links
# 3.1 Unload Revit Links (RVT)
rvt_links = list(FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements())
for link in rvt_links:
    try:
        if not link.IsNestedLink and link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
            link.Unload(None)
            unloaded_rvt_count += 1
    except:
        pass

# 3.2 Remove CAD Imports/Links (DWG)
try:
    cad_ids = list(FilteredElementCollector(doc).OfClass(CADLinkType).ToElementIds())
    for c_id in cad_ids:
        try:
            doc.Delete(c_id)
            removed_links_count += 1
        except:
            pass
except:
    pass

# 3.3 Remove Point Clouds
try:
    pc_ids = list(FilteredElementCollector(doc).OfClass(PointCloudType).ToElementIds())
    for p_id in pc_ids:
        try:
            doc.Delete(p_id)
            removed_links_count += 1
        except:
            pass
except:
    pass

# 3.4 Remove Coordination Models (Navisworks) and Topography Links
# FIXED: Safe type name validation using clean strings to avoid CoordinationModelType NameError
try:
    all_types = list(FilteredElementCollector(doc).OfClass(ElementType).ToElements())
    for type_elem in all_types:
        try:
            class_string_name = str(type_elem.GetType().Name)
            if "CoordinationModelType" in class_string_name or "TopographyLinkType" in class_string_name:
                doc.Delete(type_elem.Id)
                removed_links_count += 1
        except:
            pass
except:
    pass

# Close Block 1 transaction to update database records before starting Purge
TransactionManager.Instance.TransactionTaskDone()


# =========================================================================
# BLOCK 2: DEEP SUPER PURGE OBSCURE/UNUSED ELEMENTS
# =========================================================================
while purge_cycles_count < 10:
    TransactionManager.Instance.EnsureInTransaction(doc)
    
    # Explicit C# HashSet syntax instantiation required by CPython3
    empty_set = HashSet[ElementId]()
    unused_elements = doc.GetUnusedElements(empty_set)
    unused_ids = list(unused_elements)
    
    if not unused_ids or len(unused_ids) == 0:
        TransactionManager.Instance.TransactionTaskDone()
        break 
        
    purged_this_loop = 0
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
# OUT SYSTEM OUTPUT FOR DYNAMO WINDOW
# =========================================================================
final_report = [
    "🔥 MASTER CLEANING SCRIPT EXECUTED SUCCESSFULLY 🔥",
    "-" * 50,
    "• Group Types deleted from Project Browser: {}".format(deleted_groups_count),
    "• View Templates preserved: ALL",
    "• Unplaced views deleted (3D extras + unplaced 2D): {}".format(deleted_views_count),
    "• Revit Links unloaded (RVT Unload): {}".format(unloaded_rvt_count),
    "• Removed Links/Imports (DWG, PointCloud, NWD, Topo): {}".format(removed_links_count),
    "• Total redundant elements deleted in Super Purge: {}".format(total_purged_count),
    "• Purge loop execution cycles: {}".format(purge_cycles_count),
    "-" * 50,
    "Model database fully optimized!"
]

OUT = "\n".join(final_report)
