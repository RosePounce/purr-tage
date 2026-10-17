# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program (see the LICENSE file). If not, see
# <https://www.gnu.org/licenses/>.
"""Entry point of "Purr-tage: La Guerre des Chats".

    python main.py                      standard game (menu)
    python main.py --direct             start right away
    python main.py --difficulty tiger   hardest difficulty
    python main.py --seed 1234          replay the same map
    python main.py --language en        play in English
"""

import sys

from purrtage.app import main

if __name__ == "__main__":
    sys.exit(main())
