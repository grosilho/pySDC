from pySDC.core.SpaceTransfer import space_transfer
from pySDC.projects.Monodomain.transfer_classes.Transfer_FD_Vector import FD_to_FD
from pySDC.projects.Monodomain.datatype_classes.VectorOfVectors import VectorOfVectors


class TransferVectorOfFDVectors(space_transfer):
    """
    This implementation can restrict and prolong between super vectors
    """

    def __init__(self, fine_prob, coarse_prob, params):
        """
        Initialization routine

        Args:
            fine_prob: fine problem
            coarse_prob: coarse problem
            params: parameters for the transfer operators
        """

        # invoke super initialization
        super(TransferVectorOfFDVectors, self).__init__(fine_prob, coarse_prob, params)

        self.FD_to_FD = FD_to_FD(fine_prob, coarse_prob, params)

    def restrict(self, F):
        """
        Restriction implementation

        Args:
            F: the fine level data
        """
        u_coarse = VectorOfVectors(init=self.coarse_prob.init, val=0.0, type_sub_vector=self.coarse_prob.vector_type, size=self.coarse_prob.size)

        if self.params.fine_to_coarse[0] == 'restriction':
            u_coarse.val_list[0].values[:] = self.FD_to_FD.restrict(F[0]).values
        else:
            u_coarse.val_list[0].values[:] = self.FD_to_FD.inject(F[0]).values

        if self.params.fine_to_coarse[1] == 'restriction':
            for i in range(1, u_coarse.size):
                u_coarse.val_list[i].values[:] = self.FD_to_FD.restrict(F[i]).values
        else:
            for i in range(1, u_coarse.size):
                u_coarse.val_list[i].values[:] = self.FD_to_FD.inject(F[i]).values

        return u_coarse

    def prolong(self, G):
        """
        Prolongation implementation

        Args:
            G: the coarse level data
        """
        u_fine = VectorOfVectors(init=self.fine_prob.init, val=0.0, type_sub_vector=self.fine_prob.vector_type, size=self.fine_prob.size)
        for i in range(u_fine.size):
            u_fine.val_list[i].values[:] = self.FD_to_FD.prolong(G[i]).values

        return u_fine