import os
from pySDC.projects.Monodomain.run_scripts.run_MonodomainODE_cli_slurm_wrapper import (
    execute_with_dependencies,
    options_command,
)


def main():
    local = False
    list_n_time_ranks = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]

    slurm_options = dict()
    slurm_options["cluster"] = "eiger"

    # define sweeper parameters
    options = dict()
    options["integrator"] = "IMEXEXP_EXPRK"
    options["num_nodes"] = [8, 4]
    options["num_sweeps"] = [1]

    # set step parameters
    options["max_iter"] = 21

    # set space discretization
    options["space_disc"] = "DCT"

    # set level parameters
    # options["dt"] = 0.2
    dt_list = [0.0125]  # , 0.025, 0.05, 0.1]  # , 0.2]
    options["restol"] = 5e-8

    # set time parallelism to True or emulated (False)
    options["truly_time_parallel"] = True

    # set problem parameters
    options["domain_name"] = "cube_2D"
    options["pre_refinements"] = [0]
    options["order"] = 4
    options["lin_solv_max_iter"] = 1000000
    options["lin_solv_rtol"] = 1e-8
    ionic_models_list = ["TTP"]
    options["read_init_val"] = True
    options["init_time"] = 2500.0
    options["enable_output"] = False
    options["write_as_reference_solution"] = False
    options["output_root"] = "results_stability"
    options["mass_lumping"] = True
    options["mass_rhs"] = "none"
    options["skip_res"] = True

    options["print_stats"] = True

    n_space_ranks = 12 if options["space_disc"] == "FEM" else 1

    slurm_options["dry_run"] = False
    slurm_options["overwrite_existing_results"] = False
    slurm_options["ntaskspernode"] = 4 if slurm_options["cluster"] == "eiger" else 12
    minutes = 0
    hours = 4
    slurm_options["run_time"] = 3600 * hours + 60 * minutes

    dependencies = False
    job_number = 0

    base_python_command = "python3 run_MonodomainODE_cli.py"
    local_docker_command = (
        "docker exec -w /src/pySDC/pySDC/projects/Monodomain/run_scripts -it my_dolfinx_daint_container_monodomain_new "
    )

    for ionic_model_name in ionic_models_list:
        options["ionic_model_name"] = ionic_model_name
        for dt in dt_list:
            options["dt"] = dt
            for n_time_ranks in list_n_time_ranks:
                options["n_time_ranks"] = n_time_ranks
                options["end_time"] = options["dt"] * options["n_time_ranks"]
                num_nodes_str = "-".join([str(num_node) for num_node in options["num_nodes"]])
                pre_refinements_str = "-".join([str(pre_refinement) for pre_refinement in options["pre_refinements"]])
                options["output_file_name"] = (
                    "pre_refinements_"
                    + pre_refinements_str
                    + "_num_nodes_"
                    + num_nodes_str
                    + "_dt_"
                    + str(options["dt"]).replace(".", "p")
                    + "_n_time_ranks_"
                    + str(n_time_ranks)
                )
                n_tasks = n_space_ranks * n_time_ranks
                if local:
                    os.system(
                        local_docker_command
                        + f"mpirun -n {n_tasks} "
                        + base_python_command
                        + " "
                        + options_command(options)
                    )
                else:
                    slurm_options["n_tasks"] = n_tasks
                    merged_opts = options.copy()
                    merged_opts.update(slurm_options)
                    job_number = execute_with_dependencies(base_python_command, merged_opts, job_number, dependencies)


if __name__ == "__main__":
    main()
