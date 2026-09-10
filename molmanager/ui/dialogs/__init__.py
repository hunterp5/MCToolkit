# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Modal and modeless tool dialogs (split into submodules for maintainability)."""

from __future__ import annotations

from ..plot import PlotDialog
from ..sketcher import SketchWidget, SketcherDialog
from .calculator import CalculatorDialog
from .bulk_similarity import BulkSimilarityDialog
from .cluster import ClusterDialog
from .diverse_subset import DiverseSubsetDialog
from .fp_similarity import FPSimilarityDialog
from .mol_tools import (
    CoreBasedDecompDialogParams,
    CoreBasedDecompositionDialog,
    DisconnectFragmentsDialog,
    FastPrepareDialog,
    AddExplicitHydrogensDialog,
    RemoveExplicitHydrogensDialog,
    NeutralizeDialog,
    FragmentDecompDialogParams,
    FragmentDecompositionDialog,
    FragmentRecompDialogParams,
    FragmentRecompositionDialog,
    GenerateConformationsDialog,
    SuperposeConformersDialog,
    SuperposeStructuresDialog,
)
from .mmp import MmpDialog, MmpDialogParams
from .activity_cliff import ActivityCliffDialog, ActivityCliffDialogParams
from .mmp_neighborhood import MmpNeighborhoodDialog, MmpNeighborhoodDialogParams
from .sali import SaliDialog, SaliDialogParams
from .random_molecule import RandomMoleculeDialog, RandomMoleculeDialogParams
from .random_number import RandomNumberDialog, RandomNumberDialogParams
from .permeability import PermeabilityPredictorDialog
from .pka import PKaPredictorDialog
from .som import SomPredictorDialog
from .properties import PropertyDialog
from .protomer import ProtomerGeneratorDialog
from .pdbqt_generator import PdbqtGeneratorDialog
from .protonate import ProtonateDialog
from .easydock import EasyDockDialog
from .qsar import QSARDialog
from .mpo_scoring import MPOScoringDialog, MPOScoringDialogParams
from .reaction_enumeration import ReactionEnumerationDialog
from .render_2d import Render2DStructureDialog
from .scope import selection_scope_checked

__all__ = [
    "ActivityCliffDialog",
    "ActivityCliffDialogParams",
    "MmpNeighborhoodDialog",
    "MmpNeighborhoodDialogParams",
    "SaliDialog",
    "SaliDialogParams",
    "BulkSimilarityDialog",
    "CalculatorDialog",
    "ClusterDialog",
    "CoreBasedDecompDialogParams",
    "CoreBasedDecompositionDialog",
    "DisconnectFragmentsDialog",
    "FastPrepareDialog",
    "AddExplicitHydrogensDialog",
    "RemoveExplicitHydrogensDialog",
    "NeutralizeDialog",
    "FragmentDecompDialogParams",
    "FragmentDecompositionDialog",
    "FragmentRecompDialogParams",
    "FragmentRecompositionDialog",
    "DiverseSubsetDialog",
    "EasyDockDialog",
    "FPSimilarityDialog",
    "GenerateConformationsDialog",
    "MmpDialog",
    "MmpDialogParams",
    "PermeabilityPredictorDialog",
    "PKaPredictorDialog",
    "SomPredictorDialog",
    "PlotDialog",
    "PropertyDialog",
    "ProtomerGeneratorDialog",
    "PdbqtGeneratorDialog",
    "ProtonateDialog",
    "QSARDialog",
    "MPOScoringDialog",
    "MPOScoringDialogParams",
    "RandomMoleculeDialog",
    "RandomMoleculeDialogParams",
    "RandomNumberDialog",
    "RandomNumberDialogParams",
    "ReactionEnumerationDialog",
    "Render2DStructureDialog",
    "SketchWidget",
    "SketcherDialog",
    "SuperposeConformersDialog",
    "SuperposeStructuresDialog",
    "selection_scope_checked",
]
