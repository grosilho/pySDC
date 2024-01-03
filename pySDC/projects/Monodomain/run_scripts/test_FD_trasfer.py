from collections import namedtuple
from pathlib import Path

import numpy as np

from pySDC.projects.Monodomain.problem_classes.MonodomainODE import MonodomainODE
from pySDC.projects.Monodomain.problem_classes.space_discretizazions.Parabolic_FD import Parabolic_FD
from pySDC.projects.Monodomain.transfer_classes.Transfer_FD_Vector import FD_to_FD
from pySDC.projects.Monodomain.datatype_classes.FD_Vector import FD_Vector

import matplotlib
import matplotlib.pyplot as plt

# setup id for gathering the results (will sort by nvars)
ID = namedtuple('ID', 'n_ref_fine')


def main():
    # initialize problem parameters
    problem_params = dict()
    problem_params["pre_refinements"] = 2
    # problem_params["post_refinements"] = [0]
    # problem_params["meshes_fibers_root_folder"] = "/../../../../../meshes_fibers_fibrosis/results"
    problem_params["domain_name"] = 'cuboid_2D_small'
    problem_params["solver_rtol"] = 1e-8
    problem_params["parabolic_class"] = Parabolic_FD
    problem_params["ionic_model_name"] = 'HH'
    problem_params["read_init_val"] = False
    problem_params["init_val_name"] = "init_val"
    problem_params["istim_dur"] = 0.0 if problem_params["read_init_val"] else -1.0
    problem_params["enable_output"] = False
    problem_params["output_V_only"] = True
    problem_params["output_root"] = "/../../../../data/Monodomain/results_tmp"
    problem_params["output_file_name"] = "monodomain"
    problem_params["ref_sol"] = "ref_sol"
    problem_params["end_time"] = 1.0

    # initialize transfer parameters
    space_transfer_params = dict()
    space_transfer_params['rorder'] = 2
    space_transfer_params['iorder'] = 4
    space_transfer_params['periodic'] = False
    space_transfer_params['equidist_nested'] = False

    dim = int(problem_params["domain_name"][7])
    n_ref_fine = [p for p in range(2, 6)]

    results_prolong = []
    results_restrict = []

    freqs = np.array([4, 4, 2])
    freqs = freqs[:dim]

    for n_ref in n_ref_fine:
        print('Working on n_ref_fine = %4i...' % n_ref)

        # instantiate fine problem
        problem_params["pre_refinements"] = n_ref
        Pfine = MonodomainODE(**problem_params)

        # instantiate coarse problem using half of the DOFs
        problem_params["pre_refinements"] = n_ref - 1
        Pcoarse = MonodomainODE(**problem_params)

        # instantiate spatial interpolation
        T = FD_to_FD(fine_prob=Pfine, coarse_prob=Pcoarse, params=space_transfer_params)

        # set exact fine solution to compare with
        xvalues_fine = Pfine.parabolic.grids
        uexact_fine = FD_Vector(Pfine.init)
        cos_xyz = [np.cos(np.pi * freq * x / (x.max() - x.min())) for freq, x in zip(freqs, xvalues_fine)]
        ue = 1.0
        for i in range(len(cos_xyz)):
            ue = ue * cos_xyz[i]
        uexact_fine.values[:] = ue.ravel()

        # set exact coarse solution as source
        xvalues_coarse = Pcoarse.parabolic.grids
        uexact_coarse = FD_Vector(Pcoarse.init)
        cos_xyz = [np.cos(np.pi * freq * x / (x.max() - x.min())) for freq, x in zip(freqs, xvalues_coarse)]
        ue = 1.0
        for i in range(len(cos_xyz)):
            ue = ue * cos_xyz[i]
        uexact_coarse.values[:] = ue.ravel()

        # do the interpolation/prolongation
        u_prolong = T.prolong(uexact_coarse)
        results_prolong.append(abs(u_prolong - uexact_fine))

        u_restrict = T.restrict(uexact_fine)
        results_restrict.append(abs(u_restrict - uexact_coarse))

        if dim == 1:
            pass
            # fig, ax = plt.subplots(1, 1)
            # ax.plot(xvalues_fine[0], uexact_fine.values, label='fine')
            # ax.plot(xvalues_fine[0], u_prolong.values, label='prolong')
            # ax.plot(xvalues_coarse[0], uexact_coarse.values, label='coarse')
            # ax.plot(xvalues_coarse[0], u_restrict.values, label='restrict')
            # ax.legend()
        elif dim == 2:
            pass
            # fig, axs = plt.subplots(3, 1)
            # for ax in axs:
            #     ax.set(xlabel="x [mm]", ylabel="y [mm]")
            #     ax.set_aspect(aspect="equal")
            # axs[0].pcolormesh(xvalues_coarse[0], xvalues_coarse[1], uexact_coarse.values.reshape(Pcoarse.parabolic.NDim_FD.shape), cmap=plt.cm.jet)
            # axs[1].pcolormesh(xvalues_coarse[0], xvalues_coarse[1], u_restrict.values.reshape(Pcoarse.parabolic.NDim_FD.shape), cmap=plt.cm.jet)
            # axs[2].pcolormesh(
            #     xvalues_coarse[0], xvalues_coarse[1], uexact_coarse.values.reshape(Pcoarse.parabolic.NDim_FD.shape) - u_restrict.values.reshape(Pcoarse.parabolic.NDim_FD.shape), cmap=plt.cm.jet
            # )
            # plt.show()

    print(f'Prolongation errors: {results_prolong}')
    print(f'Restriction errors: {results_restrict}')

    # print out and check
    print('Running order checks...')
    orders_prolong = []
    orders_restrict = []
    # loop over two consecutive errors/nvars pairs
    for i in range(1, len(results_prolong)):
        orders_prolong.append(np.log(results_prolong[i - 1] / results_prolong[i]) / np.log(2))
        orders_restrict.append(np.log(results_restrict[i - 1] / results_restrict[i]) / np.log(2))

    for p in range(len(orders_prolong)):
        out = 'Prolong:  expected order %2i, got order %5.2f, deviation of %5.2f%%' % (
            space_transfer_params['iorder'],
            orders_prolong[p],
            100 * abs(space_transfer_params['iorder'] - orders_prolong[p]) / space_transfer_params['iorder'],
        )
        print(out)
        out = 'Restrict: expected order %2i, got order %5.2f, deviation of %5.2f%%' % (
            space_transfer_params['rorder'],
            orders_restrict[p],
            100 * abs(space_transfer_params['rorder'] - orders_restrict[p]) / space_transfer_params['rorder'],
        )
        print(out)


if __name__ == "__main__":
    main()
