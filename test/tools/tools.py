#
# DCore -- Integrated DMFT software for correlated electrons
# Copyright (C) 2017 The University of Tokyo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
from __future__ import print_function

import numpy
import h5py

def test_spin_moments_sh():
    from dcore.tools import spin_moments_sh

    # (Sx, Sy, Sz) = (0, 0, 1/2)
    dm_sh = [{'ud': numpy.array([[1, 0], [0, 0]])}]
    assert numpy.allclose(spin_moments_sh(dm_sh)[0], numpy.array([0.0, 0.0, 0.5]) )
    
    dm_sh = [{'up': numpy.array([[1]]), 'down': numpy.array([[0]])}]
    assert numpy.allclose(spin_moments_sh(dm_sh)[0], numpy.array([0.0, 0.0, 0.5]) )
    
    # (Sx, Sy, Sz) = (1/2, 0, 0)
    dm_sh = [{'ud': 0.5*numpy.ones((2,2))}]
    assert numpy.allclose(spin_moments_sh(dm_sh)[0], numpy.array([0.5, 0.0, 0.0]) )

    # Two-orbital case
    norb = 2
    dm_mat = numpy.zeros((2,norb,2,norb))
    for iorb in range(norb):
        dm_mat[:,iorb,:,iorb] = numpy.array([[1, 0], [0, 0]])
    dm_sh = [{'ud': dm_mat.reshape(2*norb,2*norb)}]
    assert numpy.allclose(spin_moments_sh(dm_sh)[0], numpy.array([0, 0, norb*0.5]) )

def test_save_load_Sigma_iw():
    from dcore.tools import make_block_gf, save_Sigma_iw_sh_txt, load_Sigma_iw_sh_txt
    from dcore.tools import make_block_gf, save_giw, load_giw
    from dcore.pytriqs_gf_compat import GfImFreq

    nsh = 2
    norb = 2
    beta = 10.0
    n_points = 10

    for spin_names in [['ud'], ['up', 'down']]:
        gf_struct = {sp : numpy.arange(norb) for sp in spin_names}

        Sigma_iw_sh = [make_block_gf(GfImFreq, gf_struct, beta, n_points) for ish in range(nsh)]

        for ish in range(nsh):
            for sp in spin_names:
                Sigma_iw_sh[ish][sp].data[:,:,:] = numpy.random.randn(2*n_points, norb, norb) + 1J * numpy.random.randn(2*n_points, norb, norb)
                Sigma_iw_sh[ish][sp].tail.data[...] = numpy.random.randn(*Sigma_iw_sh[ish][sp].tail.data.shape)

        save_Sigma_iw_sh_txt('Sigma_iw_sh.txt', Sigma_iw_sh, spin_names)


        Sigma_iw_sh_loaded = [s.copy() for s in Sigma_iw_sh]
        for ish in range(nsh):
            Sigma_iw_sh_loaded[ish].zero()

        load_Sigma_iw_sh_txt('Sigma_iw_sh.txt', Sigma_iw_sh_loaded, spin_names)

        mesh_points = lambda mesh: numpy.array([complex(x) for x in mesh])

        for ish in range(nsh):
            for sp in spin_names:
                numpy.allclose(mesh_points(Sigma_iw_sh[ish][sp].mesh), mesh_points(Sigma_iw_sh_loaded[ish][sp].mesh))
                numpy.allclose(Sigma_iw_sh[ish][sp].data, Sigma_iw_sh_loaded[ish][sp].data)

        # HDF5
        Sigma_iw_sh0 = Sigma_iw_sh[0][spin_names[0]]
        with h5py.File('sigma.h5', 'w') as ar:
            save_giw(ar, '/sigma_iw',  Sigma_iw_sh0)

        Sigma_iw_sh0_loaded = Sigma_iw_sh0.copy()
        with h5py.File('sigma.h5', 'r') as ar:
            load_giw(ar, '/sigma_iw', Sigma_iw_sh0_loaded)


        numpy.allclose(Sigma_iw_sh0.data, Sigma_iw_sh0_loaded.data)
        numpy.allclose(Sigma_iw_sh0.tail.data, Sigma_iw_sh0_loaded.tail.data)

test_spin_moments_sh()
test_save_load_Sigma_iw()
