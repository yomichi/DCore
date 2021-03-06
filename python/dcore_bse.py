#!/usr/bin/env python
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

import os
import sys
import copy

from .dmft_core import DMFTCoreSolver
from .program_options import create_parser
from . import sumkdft
from .tools import *
import impurity_solvers


def calc_g2_in_impurity_model(solver_name, solver_params, mpirun_command, basis_rot, Umat, gf_struct, beta, n_iw, n_tau,
                              Sigma_iw, Gloc_iw, num_wb, num_wf, ish):
    """

    Calculate G2 in an impurity model

    """

    Solver = impurity_solvers.solver_classes[solver_name]

    raise_if_mpi_imported()

    sol = Solver(beta, gf_struct, Umat, n_iw, n_tau)

    G0_iw = dyson(Sigma_iw=Sigma_iw, G_iw=Gloc_iw)
    sol.set_G0_iw(G0_iw)

    # Compute rotation matrix to the diagonal basis if supported
    rot = compute_diag_basis(G0_iw) if basis_rot else None
    s_params = copy.deepcopy(solver_params)
    s_params['random_seed_offset'] = 1000 * ish

    s_params['num_wb'] = num_wb
    s_params['num_wf'] = num_wf

    work_dir_org = os.getcwd()
    work_dir = 'work/imp_shell' + str(ish) + '_bse'
    if not os.path.isdir(work_dir):
        os.makedirs(work_dir)
    os.chdir(work_dir)

    # Solve the model
    xloc = sol.calc_g2(rot, mpirun_command, s_params)

    os.chdir(work_dir_org)

    return xloc, sol.get_Gimp_iw()


def subtract_disconnected(xloc, gimp, spin_names):
    """
    subtract disconnected part from X_loc
        X_loc[(i1, i2, i3, i4)][wb=0, wf1, wf2] - G[(i2, i1)][wf1] * G[(i3, i4)][wf2]

    """

    # g_ij[(i, j)] = data[iw]
    g_ij = {}
    for isp, sp in enumerate(spin_names):
        # data[iw, orb1, orb2]
        norb = gimp[sp].data.shape[1]
        assert norb == gimp[sp].data.shape[2]
        for o1, o2 in product(range(norb), repeat=2):
            i = o1 + isp*norb
            j = o2 + isp*norb
            g_ij[(i, j)] = gimp[sp].data[:, o1, o2]

    assert g_ij[(0, 0)].shape[0] % 2 == 0
    w0 = g_ij[(0, 0)].shape[0] / 2

    def g(_i, _j, _w):
        return g_ij[(_i, _j)][w0 + _w]

    for (i1, i2, i3, i4), data in xloc.items():
        n_wf = data.shape[1]
        assert n_wf == data.shape[2]
        assert n_wf % 2 == 0

        # skip if g_ij has no data
        if (not (i2, i1) in g_ij) or (not (i3, i4) in g_ij):
            continue

        for if1, if2 in product(range(n_wf), repeat=2):
            wf1 = if1 - n_wf/2
            wf2 = if2 - n_wf/2
            data[0, if1, if2] -= g(i2, i1, wf1) * g(i3, i4, wf2)


class SaveBSE:

    def __init__(self, h5_file, bse_info, n_corr_shells, n_flavors, use_spin_orbit, nonlocal_order_parameter, beta,
                 spin_names, bse_grp=''):

        from dft_tools.index_pair import IndexPair, IndexPair2
        from bse_tools.h5bse import h5BSE

        self.spin_names = spin_names
        self.use_spin_orbit = use_spin_orbit
        self.n_flavors = n_flavors

        only_diagonal = not nonlocal_order_parameter

        n_block = 2 if not use_spin_orbit else 1
        n_inner = n_flavors // n_block
        self.n_orb = n_flavors // 2
        assert n_block == len(spin_names)

        # NOTE: change the order of spins in HDF5 to meet SumkDFTChi
        self.block2 = IndexPair2(range(n_corr_shells), sorted(spin_names), only_diagonal1=only_diagonal)
        self.inner2 = IndexPair(range(n_inner), convert_to_int=True)
        print(" block2 namelist =", self.block2.namelist)
        print(" inner2 namelist =", self.inner2.namelist)

        self.h5bse = h5BSE(h5_file, bse_grp)
        if bse_info == 'check':
            # check equivalence of info
            assert self.h5bse.get(key=('block_name',)) == self.block2.namelist
            assert self.h5bse.get(key=('inner_name',)) == self.inner2.namelist
            assert self.h5bse.get(key=('beta',)) == beta
        elif bse_info == 'save':
            # save info
            self.h5bse.save(key=('block_name',), data=self.block2.namelist)
            self.h5bse.save(key=('inner_name',), data=self.inner2.namelist)
            self.h5bse.save(key=('beta',), data=beta)
        else:
            raise ValueError("bse_info =", bse_info)

    def save_xloc(self, xloc_ijkl, icrsh):

        n_inner2 = len(self.inner2.namelist)
        n_w2b = xloc_ijkl[xloc_ijkl.keys()[0]].shape[0]

        def decompose_index(index):
            spn = index // self.n_orb
            orb = index % self.n_orb
            return self.spin_names[spn], orb

        # read X_loc data and save into h5 file
        for wb in range(n_w2b):
            # boson freq
            xloc_bse = {}
            for (i1, i2, i3, i4), data in xloc_ijkl.items():
                # (wb, wf1, wf2) --> (wf1, wf2)
                data_wb = data[wb]

                if not self.use_spin_orbit:
                    s1, o1 = decompose_index(i1)
                    s2, o2 = decompose_index(i2)
                    s3, o3 = decompose_index(i3)
                    s4, o4 = decompose_index(i4)
                else:
                    s1, o1 = 0, i1
                    s2, o2 = 0, i2
                    s3, o3 = 0, i3
                    s4, o4 = 0, i4

                s12 = self.block2.get_index(icrsh, s1, icrsh, s2)
                s34 = self.block2.get_index(icrsh, s3, icrsh, s4)
                inner12 = self.inner2.get_index(o1, o2)
                inner34 = self.inner2.get_index(o3, o4)

                if (s12, s34) not in xloc_bse:
                    xloc_bse[(s12, s34)] = numpy.zeros((n_inner2, n_inner2) + data_wb.shape, dtype=complex)
                xloc_bse[(s12, s34)][inner12, inner34, :, :] = data_wb[:, :]

            # save
            self.h5bse.save(key=('X_loc', wb), data=xloc_bse)

    def save_gamma0(self, u_mat, icrsh):

        assert u_mat.shape == (self.n_flavors, )*4

        # transpose U matrix into p-h channel, c_1^+ c_2 c_4^+ c_3
        u_mat_ph1 = u_mat.transpose(0, 2, 3, 1)
        u_mat_ph2 = u_mat.transpose(0, 3, 2, 1)

        if not self.use_spin_orbit:
            u_mat_ph1 = u_mat_ph1.reshape((2, self.n_orb)*4)
            u_mat_ph2 = u_mat_ph2.reshape((2, self.n_orb)*4)

            gamma0 = {}
            for s1, s2, s3, s4 in product(range(2), repeat=4):
                gamma0_orb = - u_mat_ph1[s1, :, s2, :, s3, :, s4, :] + u_mat_ph2[s1, :, s2, :, s3, :, s4, :]

                # skip if zero
                if numpy.linalg.norm(gamma0_orb) == 0:
                    continue

                s12 = self.block2.get_index(icrsh, self.spin_names[s1], icrsh, self.spin_names[s2])
                s34 = self.block2.get_index(icrsh, self.spin_names[s3], icrsh, self.spin_names[s4])

                gamma0[(s12, s34)] = gamma0_orb.reshape((self.n_orb**2, )*2)

            self.h5bse.save(key=('gamma0', ), data=gamma0)
        else:
            gamma0_inner = - u_mat_ph1 + u_mat_ph2
            gamma0_inner = gamma0_inner.reshape((len(self.inner2.namelist), )*2)
            block_index = self.block2.get_index(icrsh, self.spin_names[0], icrsh, self.spin_names[0])
            self.h5bse.save(key=('gamma0', ), data={(block_index, block_index): gamma0_inner})


class DMFTBSESolver(DMFTCoreSolver):
    def __init__(self, seedname, params, output_file='', output_group='dmft_out'):
        assert params['control']['restart']

        super(DMFTBSESolver, self).__init__(seedname, params, output_file, output_group, read_only=True)

    def _calc_bse_x0q(self):
        """
        Calc X_0(q)
        """
        print("\n--- dcore_bse - X_0(q)")
        if self._params['bse']['skip_X0q_if_exists'] and os.path.exists(self._params['bse']['h5_output_file']):
            print(" skip")
            return

        from .lattice_model import create_lattice_model

        lattice_model = create_lattice_model(self._params)

        params = self._make_sumkdft_params()
        params['calc_mode'] = 'bse'
        params['mu'] = self._chemical_potential
        params['list_wb'] = numpy.arange(self._params['bse']['num_wb']).tolist()
        params['n_wf_G2'] = self._params['bse']['num_wf']
        params['div'] = lattice_model.nkdiv()
        params['bse_h5_out_file'] = os.path.abspath(self._params['bse']['h5_output_file'])
        params['use_temp_file'] = self._params['bse']['use_temp_file']
        if self._params['bse']['X0q_qpoints_saved'] == 'quadrant':
            params['X0q_qpoints_saved'] = 'quadrant'
        else:
            q_points = []
            with open(self._params['bse']['X0q_qpoints_saved'], 'r') as f:
                for line in f:
                    q_str = line.split()[1]
                    q_points.append(tuple(map(int, q_str.split('.'))))
            params['X0q_qpoints_saved'] = q_points
        sumkdft.run(os.path.abspath(self._seedname + '.h5'), './work/sumkdft_bse', self._mpirun_command, params)

    def _calc_bse_xloc(self):
        """
        Calc X_loc and U matrix
        """

        # NOTE:
        #   n_flavors may depend on ish, but present BSE code does not support it
        def calc_num_flavors(_ish):
            return numpy.sum([len(indices) for indices in self._gf_struct[_ish].values()])
        n_flavors = calc_num_flavors(0)
        for ish in range(self._n_inequiv_shells):
            assert n_flavors == calc_num_flavors(ish)

        #
        # init for saving data into HDF5
        #
        print("\n--- dcore_bse - invoking h5BSE...")
        bse = SaveBSE(
            n_corr_shells=self._n_corr_shells,
            h5_file=os.path.abspath(self._params['bse']['h5_output_file']),
            bse_info='check',
            nonlocal_order_parameter=False,
            use_spin_orbit=self._use_spin_orbit,
            beta=self._beta,
            n_flavors=n_flavors,
            spin_names=self.spin_block_names)

        #
        # save U matrix for RPA
        #
        print("\n--- dcore_bse - U matrix")
        for ish in range(self._n_inequiv_shells):
            bse.save_gamma0(self._Umat[ish], icrsh=self._sk.inequiv_to_corr[ish])

        # FIXME:
        #     Saving data should be done for all **correlated_shells** (not for inequiv_shells)
        #     Namely, we need a loop for correlated shells when n_inequiv_shells < n_corr_shells
        #assert self._n_inequiv_shells == self._n_corr_shells

        #
        # X_loc
        #
        print("\n--- dcore_bse - X_loc")
        if self._params['bse']['skip_Xloc']:
            print(" skip")
            return

        Gloc_iw_sh, _ = self.calc_Gloc()
        solver_name = self._params['impurity_solver']['name']

        for ish in range(self._n_inequiv_shells):
            print("\nSolving impurity model for inequivalent shell " + str(ish) + " ...")
            sys.stdout.flush()
            x_loc, g_imp = calc_g2_in_impurity_model(solver_name, self._solver_params, self._mpirun_command,
                                                     self._params["impurity_solver"]["basis_rotation"],
                                                     self._Umat[ish], self._gf_struct[ish], self._beta, self._n_iw,
                                                     self._n_tau,
                                                     self._sh_quant[ish].Sigma_iw, Gloc_iw_sh[ish],
                                                     self._params['bse']['num_wb'],
                                                     self._params['bse']['num_wf'], ish)
            assert isinstance(x_loc, dict)
            print("\nx_loc.keys() =", x_loc.keys())

            subtract_disconnected(x_loc, g_imp, self.spin_block_names)

            # save X_loc
            for icrsh in range(self._n_corr_shells):
                if ish == self._sk.corr_to_inequiv[icrsh]:
                    bse.save_xloc(x_loc, icrsh=icrsh)

    def calc_bse(self):
        """
        Compute data for BSE
        """
        self._calc_bse_x0q()
        self._calc_bse_xloc()


def dcore_bse(filename, np=1):
    """
    Main routine for the BSE post-processing tool

    Parameters
    ----------
    filename : string
        Input-file name
    """

    print("\n############  Reading Input File  #################\n")
    print("  Input File Name : ", filename)

    #
    # Construct a parser with default values
    #
    pars = create_parser()

    #
    # Parse keywords and store
    #
    pars.read(filename)
    p = pars.as_dict()
    seedname = p["model"]["seedname"]
    p["mpi"]["num_processes"] = np

    #
    # Load DMFT data
    #
    p['control']['restart'] = True
    solver = DMFTBSESolver(seedname, p, output_file=seedname + '.out.h5')
    if solver.iteration_number == 0:
        raise RuntimeError("Number of iterations is zero!")
    print("Number of iterations :", solver.iteration_number)

    #
    # Compute data for BSE
    #
    solver.calc_bse()

    #
    # Finish
    #
    print("\n#################  Done  #####################\n")


if __name__ == '__main__':
    import argparse
    from .option_tables import generate_all_description

    parser = argparse.ArgumentParser(
        prog='dcore_bse.py',
        description='Post-processing script for dcore (bse).',
        usage='$ dcore_bse input --np 4',
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=generate_all_description(),
        add_help=True)
    parser.add_argument('path_input_file',
                        action='store',
                        default=None,
                        type=str,
                        help="input file name."
                        )
    parser.add_argument('--np', help='Number of MPI processes', required=True)

    args = parser.parse_args()
    if os.path.isfile(args.path_input_file) is False:
        print("Input file is not exist.")
        sys.exit(-1)
    dcore_bse(args.path_input_file, int(args.np))
