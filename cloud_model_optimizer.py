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

# Import System for .NET Collections (HashSet Support)
clr.AddReference('System')
import System

# 1. ACTIVE DOCUMENT INITIALIZATION
doc = DocumentManager.Instance.CurrentDBDocument

# Reporting counters for the final log output
groups_deleted = 0
views_deleted = 0
templates_deleted = 0
rvt_unloaded = 0
links_removed = 0
total_purged = 0

# Nomes das duas únicas vistas 3D que devem ficar vivas
TARGET_3D_NAMES = ["3D EMISSÃO", "3D NAVIS", "3D EMISSAO"]
protected_template_ids = set()

# =========================================================================
# MAQUEAMENTO PRÉVIO: IDENTIFICAR E PROTEGER OS TEMPLATES DAS VISTAS 3D
# =========================================================================
all_views_collector = FilteredElementCollector(doc).OfClass(View).ToElements()

# Primeiro passo: Localizar as vistas 3D que serão salvas e mapear seus templates
for view in all_views_collector:
    if not view.IsTemplate and view.ViewType == ViewType.ThreeD:
        v_name = view.Name.upper()
        if any(target in v_name for target in TARGET_3D_NAMES):
            if view.ViewTemplateId != ElementId.InvalidElementId:
                protected_template_ids.add(view.ViewTemplateId)

# =========================================================================
# BLOCK A: GROUPS, VIEWS, TEMPLATES, AND LINK MANAGEMENT
# Executed within a single continuous transaction block to optimize speed
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

# --- STEP 1: PURGE MODEL & DETAIL GROUPS FROM THE PROJECT BROWSER ---
group_ids = FilteredElementCollector(doc).OfClass(GroupType).ToElementIds()
for g_id in group_ids:
    try:
        doc.Delete(g_id)
        groups_deleted += 1
    except: pass

# --- STEP 2: PURGE REDUNDANT 2D/3D VIEWS & UNUSED TEMPLATES ---
# Coleta todas as folhas (Sheets) para identificar quais vistas estão sendo usadas em pranchas
sheets = FilteredElementCollector(doc).OfClass(ViewSheet).ToElements()
views_on_sheets = set()
for sheet in sheets:
    for view_id in sheet.GetAllPlacedViews():
        views_on_sheets.add(view_id)

for view in all_views_collector:
    try:
        v_id = view.Id
        
        # Ignorar tabelas, gerenciadores internos e o próprio Project Browser
        if view.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
            continue
            
        # Se for um View Template
        if view.IsTemplate:
            # SÓ deleta se NÃO for o template de uma das nossas vistas 3D protegidas
            if v_id not in protected_template_ids:
                doc.Delete(v_id)
                templates_deleted += 1
            continue 

        # Se for uma Vista 3D
        if view.ViewType == ViewType.ThreeD:
            v_name = view.Name.upper()
            # Safety gate: Protege as vistas de coordenação da infraestrutura
            if any(target in v_name for target in TARGET_3D_NAMES):
                
                # --- CONFIGURAÇÃO AVANÇADA DOS TEMPLATES/VISTAS SALVAS ---
                # Se tiver template, altera o template, senão altera direto na vista
                t_id = view.ViewTemplateId
                target_config = doc.GetElement(t_id) if t_id != ElementId.InvalidElementId else view
                
                try:
                    # Desabilitar Crop Box (Evita interferência na nuvem do Navis)
                    target_config.CropBoxActive = False
                    target_config.CropBoxVisible = False
                    # Desabilitar Categoria de Anotações (Annotations)
                    target_config.AreAnnotationCategoriesHidden = True
                except: pass
                continue 
                
            # Se não for uma das salvas, apaga
            if view.CanBeDeleted():
                doc.Delete(v_id)
                views_deleted += 1
                
        # Se for uma Vista 2D (Plantas, Cortes, Elevações, Detalhes)
        elif view.ViewType in [ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation, ViewType.Section, ViewType.Detail]:
            # Se a vista NÃO estiver em nenhuma folha, passa o rodo
            if v_id not in views_on_sheets and view.CanBeDeleted():
                doc.Delete(v_id)
                views_deleted += 1
    except: pass

# --- STEP 3: LINK MANAGEMENT (Unload RVTs and Hard Delete Everything Else) ---
# 1. Unload em links Revit (.rvt) existentes
rvt_links = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements()
for link in rvt_links:
    if not link.IsNestedLink:
        try:
            if link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                link.Unload(None)
                rvt_unloaded += 1
        except: pass

# 2. Remover categoricamente todos os outros formatos (DWG, CAD, IFC, Imagens, Topo)
# Remove as instâncias inseridas (ImportInstance engloba CADs vinculados/importados e IFCs)
import_instances = FilteredElementCollector(doc).OfClass(ImportInstance).ToElementIds()
for inst_id in import_instances:
    try:
        doc.Delete(inst_id)
        links_removed += 1
    except: pass

# Remove as definições de tipo de link remanescentes e outros formatos nativos
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

# Commit Block A transactions
TransactionManager.Instance.TransactionTaskDone()


# =========================================================================
# BLOCK B: RECURSIVE DEEP PURGE OF UNUSED ELEMENTS (Cascading Garbage Collection)
# Executes inside repeated cycles to clean deep family and material dependencies
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
# FINAL BIM PERFORMANCE LOG REPORT
# =========================================================================
report_log = [
    "🔥 ALVES AEC TECH - CLOUD DELIVERY OPTIMIZER EXECUTED! 🔥",
    "-"*50,
    "• Model & Detail Groups purged from Browser: {}".format(groups_deleted),
    "• View Templates destroyed (Protected EMISSÃO/NAVIS): {}".format(templates_deleted),
    "• Redundant Views deleted (2D Unplaced & Unused 3D): {}".format(views_deleted),
    "• Revit Cloud Links safely unloaded: {}".format(rvt_unloaded),
    "• Hard links completely removed (DWG, CAD, IFC, PointCloud): {}".format(links_removed),
    "• Secondary cascading elements purged (Deep Purge): {}".format(total_purged),
    "• Optimization recursive cycles required: {}".format(loop_safety),
    "-"*50,
    "Model performance optimized. Checked View Templates: Crop Disabled, Annotations Hidden."
]

OUT = "\n".join(report_log)
