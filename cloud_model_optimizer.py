# Revit 2024 Aggressive Project Sanitizer
# Version: 1.1.0 (Fixed for CPython3 Deployment)
# Target: Revit 2024 / 2025 / 2026
# Host: Dynamo Python Script Node

import sys
import clr
import time

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
clr.AddReference("System")

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List, HashSet

doc = DocumentManager.Instance.CurrentDBDocument

DEBUG = True  # FIXED: Defaulted to True to allow logs to populate the output dictionary
PURGE_LIMIT = 10

_start = time.time()

class Logger(object):
    def __init__(self):
        self.messages = []

    def info(self, message):
        if DEBUG:
            self.messages.append("[INFO] {}".format(message))

    def warning(self, message):
        self.messages.append("[WARNING] {}".format(message))

    def error(self, message):
        self.messages.append("[ERROR] {}".format(message))

LOG = Logger()

class Stats(object):
    def __init__(self):
        self.groups = 0
        self.group_types = 0
        self.views = 0
        self.cad_instances = 0
        self.cad_types = 0
        self.links = 0
        self.purge = 0
        self.deleted = 0
        self.errors = 0

    def report(self):
        return {
            "Groups": self.groups,
            "GroupTypes": self.group_types,
            "Views": self.views,
            "CADInstances": self.cad_instances,
            "CADTypes": self.cad_types,
            "RevitLinksUnloaded": self.links,
            "Purged": self.purge,
            "Deleted": self.deleted,
            "Errors": self.errors,
            "ElapsedSeconds": round(time.time() - _start, 2),
            "Messages": LOG.messages
        }

STATS = Stats()

def net_list(ids):
    result = List[ElementId]()
    for element_id in ids:
        result.Add(element_id)
    return result

def delete_batch(ids):
    ids = list(ids)
    if not ids:
        return 0
    try:
        deleted = doc.Delete(net_list(ids))
        STATS.deleted += len(deleted)
        return len(deleted)
    except Exception as ex:
        STATS.errors += 1
        LOG.error(str(ex))
        return 0

def collector(cls):
    return FilteredElementCollector(doc).OfClass(cls)

def begin():
    TransactionManager.Instance.EnsureInTransaction(doc)

def commit():
    TransactionManager.Instance.TransactionTaskDone()

class GroupCleaner(object):
    def execute(self):
        self.delete_groups()
        self.delete_group_types()

    def delete_groups(self):
        ids = list(collector(Group).ToElementIds())
        STATS.groups = len(ids)
        delete_batch(ids)

    def delete_group_types(self):
        ids = list(collector(GroupType).ToElementIds())
        STATS.group_types = len(ids)
        delete_batch(ids)

class ViewCleaner(object):
    def __init__(self):
        self.placed = set()
        self.delete_queue = []

    def execute(self):
        self.collect_placed_views()
        self.collect_unused_views()
        STATS.views = len(self.delete_queue)
        delete_batch(self.delete_queue)

    def collect_placed_views(self):
        for sheet in collector(ViewSheet):
            try:
                for view_id in sheet.GetAllPlacedViews():
                    self.placed.add(view_id.IntegerValue)
            except:
                pass

    def protected(self, view):
        if view.IsTemplate:
            return True
        if isinstance(view, ViewSheet):
            return True
        if view.ViewType in (
            ViewType.Internal,
            ViewType.ProjectBrowser,
            ViewType.Legend,
            ViewType.DrawingSheet,
            ViewType.Schedule
        ):
            return True
        return False

    def collect_unused_views(self):
        for view in list(collector(View).ToElements()):
            try:
                if self.protected(view):
                    continue
                if view.Id.IntegerValue in self.placed:
                    continue
                if view.GetDependentViewIds().Count > 0:
                    continue
                if not view.CanBeDeleted():
                    continue
                self.delete_queue.append(view.Id)
            except Exception as ex:
                STATS.errors += 1
                LOG.error(str(ex))

class CADCleaner(object):
    def execute(self):
        self.delete_import_instances()
        self.delete_cad_links()

    def delete_import_instances(self):
        ids = list(collector(ImportInstance).ToElementIds())
        STATS.cad_instances = len(ids)
        delete_batch(ids)

    def delete_cad_links(self):
        ids = list(collector(CADLinkType).ToElementIds())
        STATS.cad_types = len(ids)
        delete_batch(ids)

class RevitLinkCleaner(object):
    def execute(self):
        self.unload_links()

    def unload_links(self):
        # FIXED: Re-engineered to strictly perform UNLOAD on RVTs, preserving network paths
        for link in list(collector(RevitLinkType).ToElements()):
            try:
                if link.IsNestedLink:
                    continue
                if link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                    link.Unload(None)
                    STATS.links += 1
            except Exception as ex:
                STATS.errors += 1
                LOG.error(str(ex))

class DeepPurgeEngine(object):
    def execute(self):
        loops = 0
        while loops < PURGE_LIMIT:
            # FIXED: Replaced raw force closures with clean native transaction tracking checkpoints
            begin()
            try:
                unused = list(doc.GetUnusedElements(HashSet[ElementId]()))
            except Exception as ex:
                STATS.errors += 1
                LOG.error(str(ex))
                commit()
                break

            if not unused:
                commit()
                break

            deleted = delete_batch(unused)
            STATS.purge += deleted
            commit()

            if deleted == 0:
                break
            loops += 1

class Controller(object):
    def __init__(self):
        self.steps = [
            GroupCleaner(),
            ViewCleaner(),
            CADCleaner(),
            RevitLinkCleaner()
        ]

    def execute(self):
        begin()
        try:
            for step in self.steps:
                step.execute()
        finally:
            commit()
            
        DeepPurgeEngine().execute()

# FIXED: Moved main execution scope safely outside the Controller class grid structure
def main():
    try:
        Controller().execute()
        return STATS.report()
    except Exception as ex:
        STATS.errors += 1
        LOG.error(str(ex))
        return STATS.report()

# Global execution node callback definition
OUT = main()
