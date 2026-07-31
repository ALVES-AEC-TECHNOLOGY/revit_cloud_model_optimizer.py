

```python
# -*- coding: utf-8 -*-
"""
Script de Limpeza de Modelo, Auditia e Emissão BIM
Autor: ALVES AEC TECHNOLOGY
Descrição: Deleta vistas redundantes (preserva folhas e templates existentes),
             descarrega links, cria e configura as vistas de entrega 3D NAVIS e 3D EMISSAO 
             junto com seus View Templates e executa o comando Purge recursivo na base de dados BIM.
"""

import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

# Importar Serviços de Transação e Documento do Dynamo
clr.AddReference('RevitServices')
import RevitServices
from RevitServices.Persistance import DocumentManager
from RevitServices.Transactions import TransactionManager

# Importar Coleções do .NET System
clr.AddReference('System.Collections.Generic')
using System;
using System.Collections.Generic;

# INICIALIZAÇÃO
doc = DocumentManager.Instance.CurrentDBDocument

# Contadores de performance para o log final do Dynamo
groups_deleted = 0
views_deleted = 0
templates_deleted = 0
rvt_unloaded = 0
links_removed = 0
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
