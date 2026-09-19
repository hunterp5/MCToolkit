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

"""RDKit Leader sphere-exclusion clustering."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.workers.cluster_worker import cluster_sphere_exclusion


def test_sphere_exclusion_assigns_nearest_centroid():
    smis = ["CCO", "CCCO", "c1ccccc1", "Cc1ccccc1", "CC(=O)O"]
    fps = [AllChem.GetMorganFingerprintAsBitVect(Chem.MolFromSmiles(s), 2, 2048) for s in smis]
    labels = cluster_sphere_exclusion(fps, 0.25)
    assert labels is not None
    assert labels.shape[0] == 5
    assert len(set(int(x) for x in labels)) >= 2


def test_sphere_exclusion_high_cutoff_yields_many_clusters():
    smis = ["CCO", "CCC", "CCCC", "CCCCC"]
    fps = [AllChem.GetMorganFingerprintAsBitVect(Chem.MolFromSmiles(s), 2, 2048) for s in smis]
    labels = cluster_sphere_exclusion(fps, 0.05)
    assert labels is not None
    assert len(set(int(x) for x in labels)) == 4


def test_butina_and_jarvis_patrick_do_not_need_dense_matrix():
    from molmanager.workers.cluster_worker import (
        _method_needs_dense_matrix,
        cluster_butina,
        cluster_jarvis_patrick,
    )

    assert not _method_needs_dense_matrix("butina")
    assert not _method_needs_dense_matrix("jarvis_patrick")
    assert not _method_needs_dense_matrix("sphere_exclusion")
    assert _method_needs_dense_matrix("kmeans")
    smis = ["CCO", "CCCO", "c1ccccc1", "Cc1ccccc1"]
    fps = [AllChem.GetMorganFingerprintAsBitVect(Chem.MolFromSmiles(s), 2, 2048) for s in smis]
    butina = cluster_butina(fps, 0.4)
    assert butina is not None
    assert butina.shape[0] == 4
    jp = cluster_jarvis_patrick(fps, nn_count=2, common_neighbors=1)
    assert jp is not None
    assert jp.shape[0] == 4
