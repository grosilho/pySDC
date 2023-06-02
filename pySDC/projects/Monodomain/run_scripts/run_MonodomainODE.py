import mpi4py

mpi4py.rc.recv_mprobe = False
from pathlib import Path
import numpy as np
from mpi4py import MPI
import logging
import os

from pySDC.core.Errors import ParameterError

from pySDC.projects.Monodomain.problem_classes.MonodomainODE import MonodomainODE, MultiscaleMonodomainODE

from pySDC.projects.Monodomain.hooks.HookClass_post_iter_info import post_iter_info_hook

from pySDC.helpers.stats_helper import get_sorted

from pySDC.projects.Monodomain.transfer_classes.my_BaseTransfer_mass import my_base_transfer_mass
from pySDC.projects.Monodomain.transfer_classes.my_BaseTransfer import my_base_transfer

from pySDC.projects.Monodomain.controller_classes.my_controller_MPI import my_controller_MPI as controller_MPI
from pySDC.projects.Monodomain.controller_classes.my_controller_nonMPI import my_controller_nonMPI as controller_nonMPI

from pySDC.projects.Monodomain.sweeper_classes.exponential_runge_kutta.imexexp_1st_order import imexexp_1st_order as imexexp_1st_order_ExpRK
from pySDC.projects.Monodomain.sweeper_classes.exponential_runge_kutta.imexexp_1st_order_mass import imexexp_1st_order_mass as imexexp_1st_order_mass_ExpRK
from pySDC.projects.Monodomain.sweeper_classes.runge_kutta.imexexp_1st_order import imexexp_1st_order

from pySDC.projects.Monodomain.sweeper_classes.exponential_runge_kutta.exponential_multirate_explicit_stabilized import (
    exponential_multirate_explicit_stabilized as exponential_multirate_explicit_stabilized_ExpRK,
)

from pySDC.projects.Monodomain.sweeper_classes.runge_kutta.multirate_explicit_stabilized import multirate_explicit_stabilized
from pySDC.projects.Monodomain.sweeper_classes.runge_kutta.exponential_multirate_explicit_stabilized import exponential_multirate_explicit_stabilized
from pySDC.projects.Monodomain.sweeper_classes.runge_kutta.explicit_stabilized import explicit_stabilized

from pySDC.projects.Monodomain.utils.data_management import database


def set_logger(controller_params):
    logging.basicConfig(level=controller_params["logger_level"])
    hooks_logger = logging.getLogger("hooks")
    hooks_logger.setLevel(controller_params["logger_level"])


def get_controller(controller_params, description, time_comm, n_time_ranks, truly_time_parallel):
    if truly_time_parallel:
        controller = controller_MPI(controller_params=controller_params, description=description, comm=time_comm)
    else:
        controller = controller_nonMPI(num_procs=n_time_ranks, controller_params=controller_params, description=description)
    return controller


def print_statistics(stats, controller, problem_params, space_rank, time_comm, output_file_name, Tend):
    iter_counts = get_sorted(stats, type="niter", sortby="time")
    niters = [item[1] for item in iter_counts]
    timing = get_sorted(stats, type="timing_run", sortby="time")
    timing = timing[0][1]
    if time_comm is not None:
        niters = time_comm.gather(niters, root=0)
        timing = time_comm.gather(timing, root=0)
    if time_comm is None or time_comm.rank == 0:
        niters = np.array(niters).flatten()
        controller.logger.info("Mean number of iterations: %4.2f" % np.mean(niters))
        controller.logger.info("Std and var for number of iterations: %4.2f -- %4.2f" % (float(np.std(niters)), float(np.var(niters))))
        timing = np.mean(np.array(timing))
        controller.logger.info(f"Time to solution: {timing:6.4f} sec.")

    from pySDC.projects.Monodomain.utils.visualization_tools import show_residual_across_simulation

    pre_ref = problem_params["pre_refinements"][0] if type(problem_params["pre_refinements"]) is list else problem_params["pre_refinements"]
    out_folder = problem_params["output_root"] + "/" + problem_params["domain_name"] + "/ref_" + str(pre_ref) + "/" + problem_params["ionic_model_name"] + "/"
    os.makedirs(out_folder, exist_ok=True)
    fname = out_folder + f"{output_file_name}_residuals.png"
    if space_rank == 0:
        show_residual_across_simulation(stats=stats, fname=fname, comm=time_comm, tend=Tend)


def print_dofs_stats(space_rank, time_rank, controller, P, uinit):
    data, avg_data = P.parabolic.get_dofs_stats()
    tot_dofs = uinit.getSize()
    mesh_dofs = uinit[0].getSize()
    if space_rank == 0 and time_rank == 0:
        controller.logger.info(f"Total dofs: {tot_dofs}, mesh dofs = {mesh_dofs}")
        for i, d in enumerate(data):
            controller.logger.info(f"Processor {i}: tot_mesh_dofs = {d[0]:.2e}, n_loc_mesh_dofs = {d[1]:.2e}, n_mesh_ghost_dofs = {d[2]:.2e}, %ghost = {100*d[3]:.2f}")
        controller.logger.info(f"Average    : tot_mesh_dofs = {avg_data[0]:.2e}, n_loc_mesh_dofs = {avg_data[1]:.2e}, n_mesh_ghost_dofs = {avg_data[2]:.2e}, %ghost = {100*avg_data[3]:.2f}")


def get_P_data(controller, truly_time_parallel):
    if truly_time_parallel:
        P = controller.S.levels[0].prob
    else:
        P = controller.MS[0].levels[0].prob
    # set time parameters
    t0 = P.t0
    Tend = P.Tend
    uinit = P.initial_value()
    return t0, Tend, uinit, P


def get_comms(n_time_ranks, truly_time_parallel):
    if truly_time_parallel:
        # set MPI communicator
        comm = MPI.COMM_WORLD
        world_rank = comm.Get_rank()
        world_size = comm.Get_size()
        assert world_size % n_time_ranks == 0, "Total number of ranks must be a multiple of n_time_ranks"
        n_space_ranks = int(world_size / n_time_ranks)
        # split world communicator to create space-communicators
        color = int(world_rank / n_space_ranks)
        space_comm = comm.Split(color=color)
        space_rank = space_comm.Get_rank()
        # split world communicator to create time-communicators
        color = int(world_rank % n_space_ranks)
        time_comm = comm.Split(color=color)
        time_rank = time_comm.Get_rank()
    else:
        space_comm = MPI.COMM_WORLD
        space_rank = space_comm.Get_rank()
        time_comm = None
        time_rank = 0
    return space_comm, time_comm, space_rank, time_rank


def get_base_transfer_params():
    base_transfer_params = dict()
    base_transfer_params["finter"] = False
    return base_transfer_params


def get_controller_params(problem_params, space_rank):
    controller_params = dict()
    controller_params["predict_type"] = "pfasst_burnin"
    # controller_params["predict_type"] = "fine_only"
    controller_params["log_to_file"] = False
    controller_params["fname"] = problem_params["output_root"] + "controller"
    controller_params["logger_level"] = 20 if space_rank == 0 else 99  # set level depending on rank
    controller_params["dump_setup"] = False
    controller_params["hook_class"] = [post_iter_info_hook]
    return controller_params


def get_description(integrator, problem_params, sweeper_params, level_params, step_params, base_transfer_params, space_transfer_class, space_transfer_params):
    description = dict()

    if integrator != "ES":
        problem = MultiscaleMonodomainODE
    else:
        problem = MonodomainODE

    if integrator != 'mES':
        problem_params["splitting"] = "exp_nonstiff"
    else:
        problem_params["splitting"] = "stiff_nonstiff"

    if integrator == "IMEXEXP":
        description["sweeper_class"] = imexexp_1st_order
    elif integrator == "IMEXEXP_EXPRK":
        if problem_params["mass_rhs"] != "none":
            description["sweeper_class"] = imexexp_1st_order_mass_ExpRK
        else:
            description["sweeper_class"] = imexexp_1st_order_ExpRK
    elif integrator == "ES":
        description["sweeper_class"] = explicit_stabilized
    elif integrator == "mES":
        description["sweeper_class"] = multirate_explicit_stabilized
    elif integrator == "exp_mES":
        description["sweeper_class"] = exponential_multirate_explicit_stabilized
    elif integrator == "exp_mES_EXPRK":
        description["sweeper_class"] = exponential_multirate_explicit_stabilized_ExpRK
    else:
        raise ParameterError("Unknown integrator.")

    description["problem_class"] = problem
    description["problem_params"] = problem_params
    description["sweeper_params"] = sweeper_params
    description["level_params"] = level_params
    description["step_params"] = step_params
    description["base_transfer_params"] = base_transfer_params
    if problem_params["mass_rhs"] != "none":
        assert problem_params["space_disc"] == "FEM", "Mass rhs only implemented for FEM"
        description["base_transfer_class"] = my_base_transfer_mass
    else:
        description["base_transfer_class"] = my_base_transfer
    description["space_transfer_class"] = space_transfer_class
    description["space_transfer_params"] = space_transfer_params
    return description


def get_step_params(maxiter):
    step_params = dict()
    step_params["maxiter"] = maxiter
    return step_params


def get_level_params(dt, nsweeps, restol):
    # initialize level parameters
    level_params = dict()
    level_params["restol"] = restol
    level_params["dt"] = dt
    level_params["nsweeps"] = nsweeps
    level_params["residual_type"] = "full_rel"
    return level_params


def get_sweeper_params(num_nodes):
    # initialize sweeper parameters
    sweeper_params = dict()
    sweeper_params["initial_guess"] = "spread"
    sweeper_params["quad_type"] = "RADAU-RIGHT"
    sweeper_params["num_nodes"] = num_nodes
    sweeper_params["QI"] = "IE"
    # specific for explicit stabilized methods
    # sweeper_params["es_class"] = "RKW1"
    # sweeper_params["es_class_outer"] = "RKW1"
    # sweeper_params["es_class_inner"] = "RKW1"
    # sweeper_params['es_s_outer'] = 0  # if given, or not zero, then the algorithm fixes s of the outer stabilized scheme to this value.
    # sweeper_params['es_s_inner'] = 0
    # # # sweeper_params['res_comp'] = 'f_eta'
    # sweeper_params["damping"] = 0.05
    # sweeper_params["safe_add"] = 0
    # sweeper_params["rho_freq"] = 100
    return sweeper_params


def get_space_tranfer_params(problem_params, iorder, rorder, fine_to_coarse):
    if problem_params["space_disc"] == 'FEM':
        from pySDC.projects.Monodomain.transfer_classes.TransferVectorOfFEniCSxVectors import TransferVectorOfFEniCSxVectors

        space_transfer_class = TransferVectorOfFEniCSxVectors
        space_transfer_params = dict()
    elif problem_params["space_disc"] == 'DCT':
        from pySDC.projects.Monodomain.transfer_classes.TransferVectorOfDCTVectors import TransferVectorOfDCTVectors

        space_transfer_class = TransferVectorOfDCTVectors
        space_transfer_params = dict()
    elif problem_params["space_disc"] == 'FD':
        from pySDC.projects.Monodomain.transfer_classes.TransferVectorOfFDVectors import TransferVectorOfFDVectors

        space_transfer_class = TransferVectorOfFDVectors
        space_transfer_params = dict()
        space_transfer_params["iorder"] = iorder
        space_transfer_params["rorder"] = rorder
        space_transfer_params["periodic"] = problem_params['bc'] == 'P'
        # space_transfer_params["equidist_nested"] = False
        space_transfer_params["fine_to_coarse"] = fine_to_coarse  # how to transfer from fine to coarse space voltage and ionic model variables

    return space_transfer_class, space_transfer_params


def get_problem_params(
    space_comm,
    domain_name,
    space_disc,
    pre_refinements,
    ionic_model_name,
    read_init_val,
    init_time,
    enable_output,
    end_time,
    bc,
    order,
    lin_solv_max_iter,
    lin_solv_rtol,
    mass_lumping,
    mass_rhs,
    output_root,
    output_file_name,
    ref_sol,
):
    # initialize problem parameters
    problem_params = dict()
    problem_params["comm"] = space_comm
    problem_params["family"] = "CG"
    problem_params["order"] = order
    problem_params["bc"] = bc
    problem_params["mass_lumping"] = mass_lumping
    problem_params["mass_rhs"] = mass_rhs
    problem_params["pre_refinements"] = pre_refinements
    problem_params["post_refinements"] = [0]
    problem_params["fibrosis"] = False
    executed_file_dir = os.path.dirname(os.path.realpath(__file__))
    problem_params["meshes_fibers_root_folder"] = executed_file_dir + "/../../../../../meshes_fibers_fibrosis/results"
    problem_params["domain_name"] = domain_name
    problem_params["lin_solv_max_iter"] = lin_solv_max_iter
    problem_params["lin_solv_rtol"] = lin_solv_rtol
    problem_params["space_disc"] = space_disc
    problem_params["ionic_model_name"] = ionic_model_name
    problem_params["read_init_val"] = read_init_val
    problem_params["init_time"] = init_time
    problem_params["init_val_name"] = "init_val_" + problem_params["space_disc"]
    problem_params["enable_output"] = enable_output
    problem_params["output_V_only"] = True
    problem_params["output_root"] = executed_file_dir + "/../../../../data/Monodomain/" + output_root
    problem_params["output_file_name"] = output_file_name
    problem_params["ref_sol"] = ref_sol
    problem_params["end_time"] = end_time
    Path(problem_params["output_root"]).mkdir(parents=True, exist_ok=True)
    return problem_params


def setup_and_run(
    integrator,
    num_nodes,
    num_sweeps,
    max_iter,
    space_disc,
    dt,
    restol,
    domain_name,
    pre_refinements,
    order,
    mass_lumping,
    mass_rhs,
    lin_solv_max_iter,
    lin_solv_rtol,
    ionic_model_name,
    read_init_val,
    init_time,
    enable_output,
    write_as_reference_solution,
    output_root,
    output_file_name,
    ref_sol,
    end_time,
    truly_time_parallel,
    n_time_ranks,
    print_stats,
):
    # get space-time communicators
    space_comm, time_comm, space_rank, time_rank = get_comms(n_time_ranks, truly_time_parallel)
    # get time integration parameters
    # set maximum number of iterations in SDC/ESDC/MLSDC/etc
    step_params = get_step_params(maxiter=max_iter)
    # set number of collocation nodes in each level
    sweeper_params = get_sweeper_params(num_nodes=num_nodes)
    # set step size, number of sweeps per iteration, and residual tolerance for the stopping criterion
    level_params = get_level_params(
        dt=dt,
        nsweeps=num_sweeps,
        restol=restol,
    )
    # get problem parameters
    problem_params = get_problem_params(
        space_comm=space_comm,
        domain_name=domain_name,
        space_disc=space_disc,
        pre_refinements=pre_refinements,
        ionic_model_name=ionic_model_name,
        read_init_val=read_init_val,
        init_time=init_time,
        enable_output=enable_output,
        end_time=end_time,
        bc='N',
        order=order,
        lin_solv_max_iter=lin_solv_max_iter,
        lin_solv_rtol=lin_solv_rtol,
        mass_lumping=mass_lumping,
        mass_rhs=mass_rhs,
        output_root=output_root,
        output_file_name=output_file_name,
        ref_sol=ref_sol,
    )

    space_transfer_class, space_transfer_params = get_space_tranfer_params(
        problem_params,
        iorder=16,
        rorder=8,
        fine_to_coarse=['restriction', 'restriction'],  # restriction or injection, for voltage and ionic model variables
    )

    # Usually do not modify below this line ------------------
    # get remaining prams
    base_transfer_params = get_base_transfer_params()
    controller_params = get_controller_params(problem_params, space_rank)
    description = get_description(integrator, problem_params, sweeper_params, level_params, step_params, base_transfer_params, space_transfer_class, space_transfer_params)
    set_logger(controller_params)
    controller = get_controller(controller_params, description, time_comm, n_time_ranks, truly_time_parallel)

    # get PDE data
    t0, Tend, uinit, P = get_P_data(controller, truly_time_parallel)

    # print dofs stats (dofs per processor, etc.)
    print_dofs_stats(space_rank, time_rank, controller, P, uinit)

    # call main function to get things done...
    uend, stats = controller.run(u0=uinit, t0=t0, Tend=Tend)

    if write_as_reference_solution:
        P.write_reference_solution(uend, Tend)

    # compute errors, if a reference solution is available
    error_availabe, error_L2, rel_error_L2 = P.compute_errors(uend)
    # error_L2, rel_error_L2 = 0, 0

    # print statistics (number of iterations, time to solution, etc.)
    if print_stats:
        print_statistics(stats, controller, problem_params, space_rank, time_comm, output_file_name, Tend)

    iter_counts = get_sorted(stats, type="niter", sortby="time")
    niters = [item[1] for item in iter_counts]
    times = [item[0] for item in iter_counts]
    cpu_time = get_sorted(stats, type="timing_run", sortby="time")
    cpu_time = cpu_time[0][1]
    if time_comm is not None:
        niters = time_comm.gather(niters, root=0)
        times = time_comm.gather(times, root=0)
        cpu_time = time_comm.gather(cpu_time, root=0)
    if time_comm is None or time_comm.rank == 0:
        niters = np.array(niters).flatten()
        times = np.array(times).flatten()
        mean_niters = np.mean(niters)
        std_niters = float(np.std(niters))
        cpu_time = np.mean(np.array(cpu_time))

    if time_comm is None or time_rank == 0:
        if space_comm is None or space_rank == 0:
            perf_data = dict()
            perf_data["niters"] = list(niters.astype(float))
            perf_data["mean_niters"] = mean_niters
            perf_data["std_niters"] = std_niters
            perf_data["times"] = list(times.astype(float))
            perf_data["error_available"] = error_availabe
            perf_data["err"] = error_L2
            perf_data["rel_err"] = rel_error_L2
            perf_data["truly_parallel"] = truly_time_parallel
            perf_data["n_time_ranks"] = n_time_ranks
            perf_data["cpu_time"] = cpu_time
            ref_sol_data_path = P.output_folder / Path(P.ref_sol)
            if ref_sol_data_path.with_suffix('.db').is_file():
                ref_sol_data = database(ref_sol_data_path)
                perf_data_ref_sol = ref_sol_data.read_dictionary("perf_data")
                perf_data["speedup"] = perf_data_ref_sol["cpu_time"] / cpu_time
                perf_data["parallel_efficiency"] = perf_data["speedup"] / n_time_ranks

            file_name = P.output_folder / Path(P.output_file_name)
            if file_name.with_suffix('.db').is_file():
                os.remove(file_name.with_suffix('.db'))
            data_man = database(file_name)
            problem_params_no_comm = problem_params
            del problem_params_no_comm["comm"]
            controller_params_no_hook = controller_params
            del controller_params_no_hook["hook_class"]
            data_man.write_dictionary("problem_params", problem_params_no_comm)
            data_man.write_dictionary("step_params", step_params)
            data_man.write_dictionary("sweeper_params", sweeper_params)
            data_man.write_dictionary("level_params", level_params)
            data_man.write_dictionary("space_transfer_params", space_transfer_params)
            data_man.write_dictionary("base_transfer_params", base_transfer_params)
            data_man.write_dictionary("controller_params", controller_params_no_hook)
            data_man.write_dictionary("perf_data", perf_data)

    # free communicators
    if truly_time_parallel:
        space_comm.Free()
        time_comm.Free()

    return error_L2, rel_error_L2


def main():
    # define sweeper parameters
    # integrator = "IMEXEXP"
    integrator = "IMEXEXP_EXPRK"
    num_nodes = [6, 4]
    num_sweeps = [1]

    # set step parameters
    max_iter = 100

    # set space discretization
    space_disc = "FD"

    # set level parameters
    dt = 0.05
    restol = 5e-8

    # set problem parameters
    domain_name = "cube_1D"
    pre_refinements = [0]
    order = 4 if space_disc == "FD" else 1
    lin_solv_max_iter = None
    lin_solv_rtol = 1e-8
    ionic_model_name = "TTP"
    read_init_val = False
    init_time = 0.0
    enable_output = False
    write_as_reference_solution = False
    end_time = 0.1
    output_root = "results_tmp"
    output_file_name = "ref_sol" if write_as_reference_solution else "monodomain"
    ref_sol = "ref_sol"
    mass_lumping = True
    mass_rhs = "none"

    # set time parallelism to True or emulated (False)
    truly_time_parallel = False
    n_time_ranks = 1
    print_stats = True

    err, rel_err = setup_and_run(
        integrator,
        num_nodes,
        num_sweeps,
        max_iter,
        space_disc,
        dt,
        restol,
        domain_name,
        pre_refinements,
        order,
        mass_lumping,
        mass_rhs,
        lin_solv_max_iter,
        lin_solv_rtol,
        ionic_model_name,
        read_init_val,
        init_time,
        enable_output,
        write_as_reference_solution,
        output_root,
        output_file_name,
        ref_sol,
        end_time,
        truly_time_parallel,
        n_time_ranks,
        print_stats,
    )


if __name__ == "__main__":
    main()