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

import glob
import re
import os
from dcore.tools import h5diff
from dcore.numdiff import numdiff
from dcore.dcore_pre import dcore_pre
from dcore.dcore import dcore
from dcore.dcore_post import dcore_post

seedname = 'test'
dcore_pre('dmft.ini')
dcore('dmft.ini')
dcore_post('dmft.ini')

data_files = glob.glob('./ref/*')

for path in data_files:
    base_name = os.path.basename(path)
    print("base_nam,e ", base_name)
    if base_name == seedname + '.h5':
        h5diff(base_name, path)
    elif base_name == seedname + '.out.h5':
        h5diff(base_name, path, "dmft_out/Sigma_iw")
    elif not re.search('.dat$', base_name) is None:
        numdiff(base_name, path)
    else:
        raise RuntimeError("Uknown how to check " + base_name)
