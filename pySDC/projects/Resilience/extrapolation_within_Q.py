import matplotlib.pyplot as plt
import numpy as np

from pySDC.implementations.convergence_controller_classes.estimate_extrapolation_error import (
    EstimateExtrapolationErrorWithinQ,
)
from pySDC.implementations.hooks.log_errors import LogLocalErrorPostStep
from pySDC.helpers.stats_helper import get_sorted

from pySDC.projects.Resilience.piline import run_piline
from pySDC.projects.Resilience.advection import run_advection


def mutiple_runs(prob, dts, Tend, num_nodes, quad_type='RADAU-RIGHT'):
    """
    Make multiple runs of a specific problem and record vital error information

    Args:
        prob (function): A problem from the resilience project to run
        dts (list): The step sizes to run with
        Tend (float): Up to where you want to run the problem
        num_nodes (int): Number of nodes
        quad_type (str): Type of nodes

    Returns:
        dict: Errors for multiple runs
        int: Order of the collocation problem
    """
    description = {}
    description['level_params'] = {'restol': 1e-12}
    description['step_params'] = {'maxiter': 99}
    description['sweeper_params'] = {'num_nodes': num_nodes, 'quad_type': quad_type}
    description['convergence_controllers'] = {EstimateExtrapolationErrorWithinQ: {}}

    res = {}

    for dt in dts:
        description['level_params']['dt'] = dt

        stats, controller, _ = prob(custom_description=description, Tend=Tend, hook_class=LogLocalErrorPostStep)

        res[dt] = {}
        res[dt]['e_loc'] = max([me[1] for me in get_sorted(stats, type='e_local_post_step')])
        res[dt]['e_ex'] = max([me[1] for me in get_sorted(stats, type='error_extrapolation_estimate')])

    coll_order = controller.MS[0].levels[0].sweep.coll.order
    return res, coll_order


def plot_and_compute_order(ax, res, num_nodes, coll_order):
    """
    Plot and compute the order from the multiple runs ran with `mutiple_runs`. Also, it is tested if the expected order
    is reached for the respective errors.

    Args:
        ax (Matplotlib.pyplot.axes): Somewhere to plot
        res (dict): Result from `mutiple_runs`
        num_nodes (int): Number of nodes
        coll_order (int): Order of the collocation problem

    Returns:
        None
    """
    dts = np.array(list(res.keys()))
    keys = list(res[dts[0]].keys())

    # local error is one order higher than global error
    expected_order = {
        'e_loc': coll_order + 1,
        'e_ex': num_nodes + 1,
    }

    for key in keys:
        errors = np.array([res[dt][key] for dt in dts])

        order = np.log(errors[1:] / errors[:-1]) / np.log(dts[1:] / dts[:-1])

        if ax is not None:
            ax.loglog(dts, errors, label=f'{key}: order={np.mean(order):.2f}')

        if key == 'e_ex':
            assert np.isclose(
                np.mean(order), expected_order[key], atol=0.5
            ), f'Expected order {expected_order[key]} for {key}, but got {np.mean(order):.2e}!'

    if ax is not None:
        ax.legend(frameon=False)


def check_order(ax, prob, dts, Tend, num_nodes, quad_type):
    """
    Check the order by calling `multiple_runs` and then `plot_and_compute_order`.

    Args:
        ax (Matplotlib.pyplot.axes): Somewhere to plot
        prob (function): A problem from the resilience project to run
        dts (list): The step sizes to run with
        Tend (float): Up to where you want to run the problem
        num_nodes (int): Number of nodes
        quad_type (str): Type of nodes
    """
    res, coll_order = mutiple_runs(prob, dts, Tend, num_nodes, quad_type)
    plot_and_compute_order(ax, res, num_nodes, coll_order)


def main():
    fig, ax = plt.subplots()
    num_nodes = 3
    quad_type = 'RADAU-RIGHT'
    check_order(ax, run_advection, [1e-1, 5e-2, 1e-2], 5e-1, num_nodes, quad_type)
    plt.show()


if __name__ == "__main__":
    main()
