import numpy as np
from dolfinx import fem, mesh, geometry
from mpi4py import MPI
import ufl
from pySDC.core.Errors import ParameterError
from pySDC.projects.ExplicitStabilized.datatype_classes.fenicsx_mesh import fenicsx_mesh
import pySDC.projects.ExplicitStabilized.problem_classes.parabolic_system_helpers.ionicmodels as ionicmodels
import pySDC.projects.ExplicitStabilized.problem_classes.parabolic_system_helpers.ionicmodels_myokit as ionicmodels_myokit

class parabolic_system_problem():
    # REDO doc
    # class defining a problem u_t - div(grad(u)) = f(t)
    # subclasses must either define self.sol_expr (ufl expression for the exact solution)
    # or self.uD and self.u0, two ufl expressions for the Dirichlet data and the initial value
    # self.rhs_expr must be defined in subclasses, it implements f(t).
    # if the exact solution is unknown (i.e. self.sol_expr not implemented), then set self.know_exact=False in subclasses
    
    def __init__(self,dim,n_elems,dom_size=[[0.,0.,0.],[1.,1.,1.]]):
        self.dom_size = dom_size
        self.define_domain(dim,n_elems)
        self.dim = self.domain.topology.dim

        # defined in subclasses
        self.size = None # number of system variables
        self.sp_ind = None # indeces of equations with non zero diffusion

        self.eval_points = np.array([])

        self.know_exact = False
        self.cte_Dirichlet = False # indicates if the Dirichlet boundary condition is constant in time
        self.rhs_or_N_bnd_dep_t = True # indicates if f(t) or the Neumann boundary data depend on t. 
        self.bnd_cond = 'N' # can be D, N or Mixed

        if self.bnd_cond not in ['D','N','Mixed']:
            raise Exception('Boundary condition must be either D,N or Mixed.')
        
    @property
    def uD_expr(self):
        return self.sol
    
    @property
    def g_expr(self):
        return self.g

    @property
    def u0_expr(self):
        self.t.value=self.t0
        return self.sol
    
    @property
    def sol_expr(self):
        return self.sol
    
    @property
    def rhs_expr(self):
        return self.rhs
    
    @property
    def rhs_stiff_expr(self):
        return self.rhs_stiff
        
    @property
    def rhs_nonstiff_expr(self):
        return self.rhs_nonstiff
    
    @property
    def rhs_expl_expr(self):
        return self.rhs_expl
    
    @property
    def lmbda_expr(self):
        return self.lmbda
    
    @property
    def yinf_expr(self):
        return self.yinf
    
    def define_domain_dependent_variables(self,domain,V,dtype_u):
        self.domain = domain
        self.V = V
        self.x = ufl.SpatialCoordinate(self.domain)
        self.n = ufl.FacetNormal(self.domain)
        self.t = fem.Constant(self.domain,0.)
        self.dt = fem.Constant(self.domain,0.)
        self.dtype_u = dtype_u
        self.uh = self.dtype_u(init=self.V,val=0.)            

    def update_time(self,t):
        if self.rhs_or_N_bnd_dep_t:
            self.t.value = t

    def update_dt(self,dt):        
        self.dt.value = dt

    def define_domain(self,dim,n_elems):
        dom_size = self.dom_size
        d = np.asarray(dom_size[1])-np.asarray(dom_size[0])
        max_d = np.max(d)
        n = [n_elems]*dim
        for i in range(len(n)):
            n[i] = int(np.ceil(n[i]*d[i]/max_d))
            
        if dim==1:
            self.domain = mesh.create_interval(comm=MPI.COMM_WORLD, nx=n_elems, points=[dom_size[0][0],dom_size[1][0]])            
        elif dim==2:            
            self.domain = mesh.create_rectangle(comm=MPI.COMM_WORLD, n=n, cell_type=mesh.CellType.triangle, points=[dom_size[0][:dim],dom_size[1][:dim]])
        elif dim==3:
            self.domain = mesh.create_box(comm=MPI.COMM_WORLD, n=n, cell_type=mesh.CellType.tetrahedron, points=[dom_size[0][:dim],dom_size[1][:dim]])
        else:
            raise ParameterError(f"need dim=1,2,3 to instantiate problem, got dim={dim}")
    
    def Dirichlet_boundary(self,x):
        if self.dim == 1:
            if self.bnd_cond=='D':
                return np.logical_or(np.isclose(x[0], self.dom_size[0][0]), np.isclose(x[0],self.dom_size[1][0]))
            elif self.bnd_cond=='Mixed':
                return np.isclose(x[0], self.dom_size[0][0])
            else:
                return [False]*len(x[0])
        elif self.dim==2:
            if self.bnd_cond=='D':
                return np.logical_or(np.logical_or(np.isclose(x[0], self.dom_size[0][0]), np.isclose(x[0],self.dom_size[1][0])),\
                                     np.logical_or(np.isclose(x[1], self.dom_size[0][1]), np.isclose(x[1],self.dom_size[1][1])))
            elif self.bnd_cond=='Mixed':
                return np.logical_or(np.isclose(x[0], self.dom_size[0][0]), np.isclose(x[0],self.dom_size[1][0]))
            else:
                return [False]*len(x[0])
        else:
            if self.bnd_cond=='D':
                return np.logical_or(np.logical_or(np.logical_or(np.isclose(x[0], self.dom_size[0][0]), np.isclose(x[0],self.dom_size[1][0])),\
                                                   np.logical_or(np.isclose(x[1], self.dom_size[0][1]), np.isclose(x[1],self.dom_size[1][1]))),\
                                    np.logical_or(np.isclose(x[2], self.dom_size[0][2]), np.isclose(x[2],self.dom_size[1][2])))
            elif self.bnd_cond=='Mixed':
                return np.logical_or(np.isclose(x[0], self.dom_size[0][0]), np.isclose(x[0],self.dom_size[1][0]))
            else:
                return [False]*len(x[0])
    
    def Neumann_boundary(self,x):        
        if self.dim == 1:
            if self.bnd_cond=='D':
                return [False]*len(x[0])
            elif self.bnd_cond=='Mixed':
                return np.isclose(x[0], self.dom_size[1][0])
            else:
                return np.logical_or(np.isclose(x[0], self.dom_size[0][0]), np.isclose(x[0],self.dom_size[1][0]))
        elif self.dim==2:
            if self.bnd_cond=='D':
                return [False]*len(x[0])
            elif self.bnd_cond=='Mixed':
                return np.logical_or(np.isclose(x[1], self.dom_size[0][1]), np.isclose(x[1],self.dom_size[1][1]))
            else:
                return np.logical_or(np.logical_or(np.isclose(x[0], self.dom_size[0][0]), np.isclose(x[0],self.dom_size[1][0])),\
                                     np.logical_or(np.isclose(x[1], self.dom_size[0][1]), np.isclose(x[1],self.dom_size[1][1])))
        else:
            if self.bnd_cond=='D':
                return [False]*len(x[0])
            elif self.bnd_cond=='Mixed':
                return np.logical_or(np.logical_or(np.isclose(x[1], self.dom_size[0][1]), np.isclose(x[1],self.dom_size[1][1])),\
                                     np.logical_or(np.isclose(x[2], self.dom_size[0][2]), np.isclose(x[2],self.dom_size[1][2])))
            else:
                return np.logical_or(np.logical_or(np.logical_or(np.isclose(x[0], self.dom_size[0][0]), np.isclose(x[0],self.dom_size[1][0])),\
                                                   np.logical_or(np.isclose(x[1], self.dom_size[0][1]), np.isclose(x[1],self.dom_size[1][1]))),\
                                    np.logical_or(np.isclose(x[2], self.dom_size[0][2]), np.isclose(x[2],self.dom_size[1][2])))


    def define_standard_splittings(self):

        # Here we define different splittings of the rhs into stiff, nonstiff and exponential terms
        self.rhs_stiff = dict()
        self.rhs_nonstiff = dict()
        self.rhs_stiff_args = dict()
        self.rhs_nonstiff_args = dict()
        self.rhs_exp_args = dict()
        self.lmbda = dict()
        self.yinf = dict()
        self.diagonal_stiff = dict()
        self.diagonal_nonstiff = dict()

        # here we consider only a stiff and a nonstiff part
        self.rhs_nonstiff['stiff_nonstiff'] = [self.rhs[0], self.rhs[1]] #this is random splitting (i.e. not really in stiff-nonstiff) just for debugging
        self.rhs_stiff['stiff_nonstiff'] = [None, None]              
        self.lmbda['stiff_nonstiff'] = [None, None]
        self.yinf['stiff_nonstiff'] = [None, None]
        self.rhs_nonstiff_args['stiff_nonstiff'] = [0,1] 
        self.rhs_stiff_args['stiff_nonstiff'] = [0,1]  # do not forget the laplacian!! it acts on both variables
        self.rhs_exp_args['stiff_nonstiff'] = [] 
        self.diagonal_nonstiff['stiff_nonstiff'] = True
        self.diagonal_stiff['stiff_nonstiff'] = False
        
        # here we add (artificially) an exponential term and remove the stiff term
        self.rhs_nonstiff['exp_nonstiff'] = [self.rhs[0], self.rhs[1] + self.sol[1]]
        self.rhs_stiff['exp_nonstiff'] = [None, None]      
        self.lmbda['exp_nonstiff'] = [None, fem.Constant(self.domain,-1.)]
        self.yinf['exp_nonstiff'] = [None, 0.]
        self.rhs_nonstiff_args['exp_nonstiff'] = [0,1] 
        self.rhs_stiff_args['exp_nonstiff'] = [0,1]  # do not forget the laplacian!! it acts on both variables
        self.rhs_exp_args['exp_nonstiff'] = [1] 
        self.diagonal_nonstiff['exp_nonstiff'] = True
        self.diagonal_stiff['exp_nonstiff'] = False

        # here we consider the three terms
        self.rhs_nonstiff['exp_stiff_nonstiff'] = [self.rhs[0], self.sol[1]]
        self.rhs_stiff['exp_stiff_nonstiff'] = [None, self.rhs[1]]      
        self.lmbda['exp_stiff_nonstiff'] = [None, fem.Constant(self.domain,-1.)]
        self.yinf['exp_stiff_nonstiff'] = [None, 0.]
        self.rhs_nonstiff_args['exp_stiff_nonstiff'] = [0,1] 
        self.rhs_stiff_args['exp_stiff_nonstiff'] = [0,1]  # do not forget the laplacian!! it acts on both variables
        self.rhs_exp_args['exp_stiff_nonstiff'] = [1] 
        self.diagonal_nonstiff['exp_stiff_nonstiff'] = True
        self.diagonal_stiff['exp_stiff_nonstiff'] = False


class linlin_solution(parabolic_system_problem):
    def __init__(self,dim,n_elems):
        dom_size=[[0.,0.,0.],[1.,1.,1.]]
        super(linlin_solution,self).__init__(dim,n_elems,dom_size)

        self.size = 2
        self.sp_ind = [0,1]

        self.alpha = 3.
        self.beta = 1.
        self.t0 = 0.0
        self.Tend = 1.
        self.diff = [0.5,0.5]        

        self.know_exact = True
        self.cte_Dirichlet = False 
        self.rhs_or_N_bnd_dep_t = True 
        self.bnd_cond = 'N' 

    def define_domain_dependent_variables(self,domain,V,dtype_u):
        super().define_domain_dependent_variables(domain,V,dtype_u)
        self.cte = fem.Constant(self.domain,self.beta)
        if self.dim==1:
            sol = 1. + self.x[0] + self.beta * self.t
        else:            
            sol = 1. + self.x[0] + self.alpha * self.x[1] + self.beta * self.t
        self.sol = [sol,sol]
        self.g = [-ufl.dot(self.diff[i]*ufl.grad(self.sol[i]),self.n) for i in range(2)]
        
        self.rhs = [self.cte,self.cte]        
        
        self.define_standard_splittings()

# class eigenfunction_laplacian(parabolic_system_problem):
#     def __init__(self,dim,n_elems):
#         dom_size=[[0.,0.,0.],[1.,1.,1.]]
#         super(eigenfunction_laplacian,self).__init__(dim,n_elems,dom_size)

#         self.size = 3
#         self.sp_ind = [i for i in range(self.size)]

#         self.t0 = 0.0
#         self.Tend = 1.
#         self.diff = [1e-1]*self.size                

#         self.know_exact = True
#         self.cte_Dirichlet = False
#         self.rhs_or_N_bnd_dep_t = True 
#         self.bnd_cond = 'N' 

#     def define_domain_dependent_variables(self,domain,V,dtype_u):
#         super().define_domain_dependent_variables(domain,V,dtype_u)
        
#         self.u0 = [ufl.cos(2.*np.pi*self.x[0]*(i+1))*ufl.cos(2.*np.pi*self.x[1]*(i+1)) for i in range(self.size)]  
#         self.sol = [ufl.exp(self.lmbda[i]*self.t)*self.u0[i] for i in range(self.size)]        

#         self.g = [fem.Constant(self.domain,0.) for _ in range(self.size)]   
#         self.rhs = [fem.Constant(self.domain,0.) for _ in range(self.size)]        

#         self.define_splittings()
        
#     def define_splittings(self):
        
#         self.rhs_stiff = dict()
#         self.rhs_nonstiff = dict()
#         self.lmbda = dict()
#         self.yinf = dict()
#         self.rhs_stiff_args = dict()

#         # here we consider only a stiff and a nonstiff part         
#         self.rhs_nonstiff['stiff_nonstiff'] = self.rhs
#         self.rhs_stiff['stiff_nonstiff'] = [None]*self.size
#         self.lmbda['stiff_nonstiff'] = [None]*self.size
#         self.yinf['stiff_nonstiff'] = [None]*self.size
        
#         self.rhs_nonstiff['exp_nonstiff'] = [-ufl.div(self.diff[i]*ufl.grad(self.sol[i])) for i in range(self.size)]
#         self.rhs_stiff['exp_nonstiff'] = [None]*self.size 
#         self.lmbda['exp_nonstiff'] = [-self.diff[i]*(i+1)**2*8.*np.pi**2 for i in range(self.size)]
#         self.yinf['exp_nonstiff']  = [0]*self.size


# class dahlquist_test_equation(parabolic_system_problem):
#     def __init__(self,dim,n_elems):
#         dom_size=[[0.,0.,0.],[1.,1.,1.]]
#         super(dahlquist_test_equation,self).__init__(dim,n_elems,dom_size)

#         self.lmbda = [-0.01, -0.1, -1., -10.]
#         self.size = len(self.lmbda)
#         self.sp_ind = [0,1,2,3]

#         self.t0 = 0.0
#         self.Tend = 1.
#         self.diff = [1e-1]*self.size                

#         self.know_exact = True
#         self.cte_Dirichlet = False
#         self.rhs_or_N_bnd_dep_t = True 
#         self.bnd_cond = 'N' 

#     def define_domain_dependent_variables(self,domain,V,dtype_u):
#         super().define_domain_dependent_variables(domain,V,dtype_u)
        

#         self.u0 = [ufl.cos(2.*np.pi*self.x[0]*(i+1))*ufl.cos(2.*np.pi*self.x[1]*(i+1)) for i in range(self.size)]  
#         self.sol = [ufl.exp(self.lmbda[i]*self.t)*self.u0[i] for i in range(self.size)]        
#         self.g = [-ufl.dot(self.diff[i]*ufl.grad(self.sol[i]),self.n) for i in range(self.size)]        
        
#         self.rhs = [-ufl.div(self.diff[i]*ufl.grad(self.sol[i])) + self.lmbda[i]*self.uh.values.sub(i) for i in range(self.size)]        

#         self.define_splittings()
        
#     def define_splittings(self):
        
#         self.rhs_stiff = dict()
#         self.rhs_nonstiff = dict()
#         self.lmbda = dict()
#         self.yinf = dict()
#         self.rhs_stiff_args = dict()

#         # here we consider only a stiff and a nonstiff part         
#         self.rhs_nonstiff['stiff_nonstiff'] = [-ufl.div(self.diff[i]*ufl.grad(self.sol[i])) for i in range(self.size)]
#         self.rhs_stiff['stiff_nonstiff'] = [self.lmbda[i]*self.uh.values.sub(i) for i in range(self.size)]
#         self.rhs_stiff_args['stiff_nonstiff'] = [0,1,2,3]
#         self.lmbda['stiff_nonstiff'] = [None]*self.size
#         self.yinf['stiff_nonstiff'] = [None]*self.size
        
#         self.rhs_nonstiff['exp_nonstiff'] = [-ufl.div(self.diff[i]*ufl.grad(self.sol[i])) for i in range(self.size)]
#         self.rhs_stiff['exp_nonstiff'] = [None]*self.size 
#         self.rhs_stiff_args['exp_nonstiff'] = [0,1,2,3]
#         self.lmbda['exp_nonstiff'] = [((ufl.exp(self.dt*self.lmbda[i])-1.)/(self.dt*self.lmbda[i]))*self.uh.values.sub(i) for i in range(self.size)]  
#         self.yinf['exp_nonstiff'] = [self.lmbda[i]*self.uh.values.sub(i) for i in range(self.size)]

#         self.rhs_nonstiff['exp_stiff_nonstiff'] = [-ufl.div(self.diff[i]*ufl.grad(self.sol[i])) for i in range(self.size)]
#         self.rhs_stiff['exp_stiff_nonstiff'] = [self.lmbda[i]*self.uh.values.sub(i) for i in range(2)]+[None,None]
#         self.rhs_stiff_args['exp_stiff_nonstiff'] = [0,1,2,3]
#         self.phi_one['exp_stiff_nonstiff'] = [None,None]+[((ufl.exp(self.dt*self.lmbda[i])-1.)/(self.dt*self.lmbda[i]))*self.uh.values.sub(i) for i in range(2,self.size)] 
#         self.rhs_exp['exp_stiff_nonstiff'] = [None,None]+[self.lmbda[i]*self.uh.values.sub(i) for i in range(2,self.size)]

# class eq_with_exp_term(parabolic_system_problem):
#     # an equation with a natural splitting into explicit part and exponential part
#     def __init__(self,dim,n_elems):
#         dom_size=[[0.,0.,0.],[1.,1.,1.]]
#         super(eq_with_exp_term,self).__init__(dim,n_elems,dom_size)

#         self.size = 2
#         self.sp_ind = [0,1]

#         self.t0 = 0.0
#         self.Tend = 1.
#         self.diff = [1e-30]*self.size                

#         self.know_exact = True
#         self.cte_Dirichlet = False
#         self.rhs_or_N_bnd_dep_t = True 
#         self.bnd_cond = 'N' 

#     def define_domain_dependent_variables(self,domain,V,dtype_u):
#         super().define_domain_dependent_variables(domain,V,dtype_u)
#         self.u0 = [ufl.cos(2.*np.pi*self.x[0]*(i+1))*ufl.cos(2.*np.pi*self.x[1]*(i+1)) for i in range(self.size)]
#         self.sol = [ self.u0[i]*ufl.exp(-self.t) + (1./6.)*(2.*ufl.exp(2.*self.t) + 3.*ufl.exp(self.t) - 9.*ufl.cos(self.t) + 9.*ufl.sin(self.t)) for i in range(self.size) ]
        
#         self.g = [-ufl.dot(self.diff[i]*ufl.grad(self.sol[i]),self.n) for i in range(self.size)]
        
#         self.rhs = [-ufl.div(self.diff[i]*ufl.grad(self.sol[i])) - self.uh.values.sub(i) + ufl.exp(2.*self.t) + ufl.exp(self.t) + 3.*ufl.sin(self.t) for i in range(self.size)]        

#         self.define_splittings()
        
#     def define_splittings(self):
        
#         self.rhs_stiff = dict()
#         self.rhs_nonstiff = dict()
#         self.rhs_exp = dict()
#         self.phi_one = dict()
#         self.rhs_stiff_args = dict()

#         # here we consider only a stiff and a nonstiff part         
#         self.rhs_nonstiff['stiff_nonstiff'] = [-ufl.div(self.diff[i]*ufl.grad(self.sol[i]))+ ufl.exp(2.*self.t) + ufl.exp(self.t) + 3.*ufl.sin(self.t) for i in range(self.size)]       
#         self.rhs_stiff['stiff_nonstiff'] = [-self.uh.values.sub(i) for i in range(self.size)] 
#         self.rhs_stiff_args['stiff_nonstiff'] = [0]
#         self.phi_one['stiff_nonstiff'] = [None]*self.size
#         self.rhs_exp['stiff_nonstiff'] = [None]*self.size
        
#         self.rhs_nonstiff['exp_nonstiff'] = [-ufl.div(self.diff[i]*ufl.grad(self.sol[i]))+ ufl.exp(2.*self.t) + ufl.exp(self.t) + 3.*ufl.sin(self.t) for i in range(self.size)]      
#         self.rhs_stiff['exp_nonstiff'] = [None]*self.size 
#         self.rhs_stiff_args['exp_nonstiff'] = [0]
#         self.phi_one['exp_nonstiff'] = [((ufl.exp(-self.dt)-1.)/(-self.dt))*self.uh.values.sub(i) for i in range(self.size)]  
#         self.rhs_exp['exp_nonstiff'] = [-self.uh.values.sub(i) for i in range(self.size)]

#         self.rhs_nonstiff['exp_stiff_nonstiff'] = self.rhs_nonstiff['exp_nonstiff']   
#         self.rhs_stiff['exp_stiff_nonstiff'] = self.rhs_stiff['exp_nonstiff']
#         self.rhs_stiff_args['exp_stiff_nonstiff'] = self.rhs_stiff_args['exp_nonstiff']
#         self.phi_one['exp_stiff_nonstiff'] = self.phi_one['exp_nonstiff']
#         self.rhs_exp['exp_stiff_nonstiff'] = self.rhs_exp['exp_nonstiff']
        
# Exactly the same as in NonLinProbDef.py, used for debugging
class coscoscos(parabolic_system_problem):
    def __init__(self,dim,n_elems,dom_size=[[0.,0.,0.],[1.,1.,1.]]):        
        super(coscoscos,self).__init__(dim,n_elems,dom_size)

        self.size = 2
        self.sp_ind = [0,1]

        self.fx = 1.
        self.fy = 1.
        self.fz = 1.
        self.ft = 1.
        self.t0 = 0.
        self.Tend = 1.
        self.diff = [0.5,0.5]

        self.know_exact = True
        self.cte_Dirichlet = False # indicates if the Dirichlet boundary condition is constant in time
        self.rhs_or_N_bnd_dep_t = True # indicates if f(t) or the Neumann boundary data depend on t. 
        self.bnd_cond = 'N' # can be D, N or Mixed

    def define_domain_dependent_variables(self,domain,V,dtype_u):
        super().define_domain_dependent_variables(domain,V,dtype_u)
        if self.dim==1:
            sol = ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.ft*self.t)     
            self.rhs = [(-ufl.pi*self.ft*ufl.sin(ufl.pi*self.ft*self.t)+self.diff[i]*ufl.pi**2*self.fx**2*ufl.cos(ufl.pi*self.ft*self.t))*ufl.cos(ufl.pi*self.fx*self.x[0]) for i in range(self.size)]
        elif self.dim==2:
            sol = ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.fy*self.x[1])*ufl.cos(ufl.pi*self.ft*self.t)       
            self.rhs = [(-ufl.pi*self.ft*ufl.sin(ufl.pi*self.ft*self.t)+self.diff[i]*ufl.pi**2*(self.fx**2+self.fy**2)*ufl.cos(ufl.pi*self.ft*self.t))*ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.fy*self.x[1]) for i in range(self.size)]
        else:
            sol = ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.fy*self.x[1])*ufl.cos(ufl.pi*self.fz*self.x[2])*ufl.cos(ufl.pi*self.ft*self.t)      
            self.rhs = [(-ufl.pi*self.ft*ufl.sin(ufl.pi*self.ft*self.t)+self.diff[i]*ufl.pi**2*(self.fx**2+self.fy**2+self.fz**2)*ufl.cos(ufl.pi*self.ft*self.t))*ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.fy*self.x[1])*ufl.cos(ufl.pi*self.fz*self.x[2]) for i in range(self.size)]
        self.sol = [sol,sol]
        self.rhs = [self.rhs[i]+self.f(self.sol[i])-self.f(self.uh.sub(i)) for i in range(self.size)]  

        self.g = [-ufl.dot(self.diff[i]*ufl.grad(self.sol[i]),self.n) for i in range(self.size)]

        self.define_standard_splittings()
    
    def f(self,u):
        return ufl.cos(u)
    
# Similar to above but the second equation is purely ODE
class coscoscos_pdeode(parabolic_system_problem):
    def __init__(self,dim,n_elems,dom_size=[[0.,0.,0.],[1.,1.,1.]]):        
        super(coscoscos_pdeode,self).__init__(dim,n_elems,dom_size)

        self.size = 2
        self.sp_ind = [0]

        self.fx = 1.
        self.fy = 1.
        self.fz = 1.
        self.ft = 1.
        self.t0 = 0.
        self.Tend = 1.
        self.diff = [0.1,None]

        self.know_exact = True
        self.cte_Dirichlet = False # indicates if the Dirichlet boundary condition is constant in time
        self.rhs_or_N_bnd_dep_t = True # indicates if f(t) or the Neumann boundary data depend on t. 
        self.bnd_cond = 'N' # can be D, N or Mixed        
        
    def define_domain_dependent_variables(self,domain,V,dtype_u):
        super().define_domain_dependent_variables(domain,V,dtype_u)
        if self.dim==1:
            sol = ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.ft*self.t)     
            self.rhs = [(-ufl.pi*self.ft*ufl.sin(ufl.pi*self.ft*self.t)+self.diff[0]*ufl.pi**2*self.fx**2*ufl.cos(ufl.pi*self.ft*self.t))*ufl.cos(ufl.pi*self.fx*self.x[0]), \
                        (-ufl.pi*self.ft*ufl.sin(ufl.pi*self.ft*self.t))*ufl.cos(ufl.pi*self.fx*self.x[0])]
        elif self.dim==2:
            sol = ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.fy*self.x[1])*ufl.cos(ufl.pi*self.ft*self.t)       
            self.rhs = [(-ufl.pi*self.ft*ufl.sin(ufl.pi*self.ft*self.t)+self.diff[0]*ufl.pi**2*(self.fx**2+self.fy**2)*ufl.cos(ufl.pi*self.ft*self.t))*ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.fy*self.x[1]),\
                        (-ufl.pi*self.ft*ufl.sin(ufl.pi*self.ft*self.t))*ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.fy*self.x[1])]
        else:
            sol = ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.fy*self.x[1])*ufl.cos(ufl.pi*self.fz*self.x[2])*ufl.cos(ufl.pi*self.ft*self.t)      
            self.rhs = [(-ufl.pi*self.ft*ufl.sin(ufl.pi*self.ft*self.t)+self.diff[0]*ufl.pi**2*(self.fx**2+self.fy**2+self.fz**2)*ufl.cos(ufl.pi*self.ft*self.t))*ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.fy*self.x[1])*ufl.cos(ufl.pi*self.fz*self.x[2]), \
                        (-ufl.pi*self.ft*ufl.sin(ufl.pi*self.ft*self.t))*ufl.cos(ufl.pi*self.fx*self.x[0])*ufl.cos(ufl.pi*self.fy*self.x[1])*ufl.cos(ufl.pi*self.fz*self.x[2])]
        self.sol = [sol,sol]
        self.g = [-ufl.dot(self.diff[0]*ufl.grad(self.sol[0]),self.n), None]
        self.rhs = [self.rhs[i]+self.f(self.sol[i])-self.f(self.uh.sub(i)) for i in range(self.size)]        
        
        self.define_standard_splittings()

    def f(self,u):
        return ufl.cos(u)
    
    def define_standard_splittings(self):
        super().define_standard_splittings()

        self.rhs_stiff_args['stiff_nonstiff'] = [0]
        self.rhs_stiff_args['exp_nonstiff'] = [0]
        self.rhs_stiff_args['exp_stiff_nonstiff'] = [0,1]

        # here we consider the three terms
        self.rhs_nonstiff['exp_nonstiff_dir_sum'] = [self.rhs[0], None]
        self.rhs_stiff['exp_nonstiff_dir_sum'] = [None, None]      
        self.lmbda['exp_nonstiff_dir_sum'] = [None, fem.Constant(self.domain,-1.)]
        self.yinf['exp_nonstiff_dir_sum'] = [None, self.rhs[1]+self.sol[1]]
        self.rhs_nonstiff_args['exp_nonstiff_dir_sum'] = [0] 
        self.rhs_stiff_args['exp_nonstiff_dir_sum'] = [0]
        self.rhs_exp_args['exp_nonstiff_dir_sum'] = [1] 
        self.diagonal_nonstiff['exp_nonstiff_dir_sum'] = True
        self.diagonal_stiff['exp_nonstiff_dir_sum'] = False

        # here we consider the three terms
        self.rhs_nonstiff['exp_stiff_nonstiff_dir_sum'] = [self.rhs[0], None]
        self.rhs_stiff['exp_stiff_nonstiff_dir_sum'] = [None, None]      
        self.lmbda['exp_stiff_nonstiff_dir_sum'] = [None, fem.Constant(self.domain,-1.)]
        self.yinf['exp_stiff_nonstiff_dir_sum'] = [None, self.rhs[1]+self.sol[1]]
        self.rhs_nonstiff_args['exp_stiff_nonstiff_dir_sum'] = [0] 
        self.rhs_stiff_args['exp_stiff_nonstiff_dir_sum'] = [0]
        self.rhs_exp_args['exp_stiff_nonstiff_dir_sum'] = [1] 
        self.diagonal_nonstiff['exp_stiff_nonstiff_dir_sum'] = True
        self.diagonal_stiff['exp_stiff_nonstiff_dir_sum'] = False

class brusselator(parabolic_system_problem):
    def __init__(self,dim,n_elems):
        dom_size=[[0.,0.,0.],[1.,1.,1.]]
        super(brusselator,self).__init__(dim,n_elems,dom_size)

        self.size = 2
        self.sp_ind = [0,1]

        self.alpha = 0.1
        self.c1 = 1.
        self.c2 = 3.4
        self.c3 = 4.4
        self.t0 = 0.0
        self.Tend = 1.
        self.diff = [self.alpha,self.alpha]

        self.know_exact = False
        self.cte_Dirichlet = False 
        self.rhs_or_N_bnd_dep_t = True 
        self.bnd_cond = 'N' 

    def define_domain_dependent_variables(self,domain,V,dtype_u):
        super().define_domain_dependent_variables(domain,V,dtype_u)    
        self.zero = fem.Constant(self.domain,0.)
        self.g = [self.zero]*self.size        
        self.u0 = [22.*self.x[1]*ufl.elem_pow(1.-self.x[1],1.5),27.*self.x[0]*ufl.elem_pow(1.-self.x[0],1.5)]        
        self.rhs = [1.0+self.uh.sub(0)**2*self.uh.sub(1)-4.4*self.uh.sub(0)+5.*ufl.exp(-((self.x[0]-0.3)**2+(self.x[1]-0.6)**2)/0.005), 3.4*self.uh.sub(0)-self.uh.sub(0)**2*self.uh.sub(1)]
        self.define_splittings()

    def define_splittings(self):
        
        # Here we define different splittings of the rhs into stiff, nonstiff and exponential terms
        self.rhs_stiff = dict()
        self.rhs_nonstiff = dict()
        self.yinf = dict()
        self.lmbda = dict()
        self.rhs_nonstiff_args = dict()
        self.rhs_stiff_args = dict()
        self.rhs_exp_args = dict()
        self.diagonal_stiff = dict()
        self.diagonal_nonstiff = dict()

        # here we consider only a stiff and a nonstiff part
        self.rhs_nonstiff['stiff_nonstiff'] = self.rhs
        self.rhs_stiff['stiff_nonstiff'] = [None,None]      
        self.rhs_stiff_args['stiff_nonstiff'] = [0,1]  # do not forget the laplacian!! it acts on both variables
        self.lmbda['stiff_nonstiff'] = [None,None]
        self.yinf['stiff_nonstiff'] = [None,None]
        self.rhs_nonstiff_args['stiff_nonstiff'] = [0,1] 
        self.rhs_stiff_args['stiff_nonstiff'] = [0,1]  # do not forget the laplacian!! it acts on both variables
        self.rhs_exp_args['stiff_nonstiff'] = [] 
        self.diagonal_nonstiff['stiff_nonstiff'] = False
        self.diagonal_stiff['stiff_nonstiff'] = False

        self.rhs_nonstiff['exp_nonstiff'] = [1.0+self.uh.sub(0)**2*self.uh.sub(1)+5.*ufl.exp(-((self.x[0]-0.3)**2+(self.x[1]-0.6)**2)/0.005), 3.4*self.uh.sub(0)-self.uh.sub(0)**2*self.uh.sub(1)]
        self.rhs_stiff['exp_nonstiff'] = [None,None]      
        self.lmbda['exp_nonstiff'] = [-4.4,None]  
        self.yinf['exp_nonstiff'] = [0.,None]
        self.rhs_nonstiff_args['exp_nonstiff'] = [0,1] 
        self.rhs_stiff_args['exp_nonstiff'] = [0,1]  # do not forget the laplacian!! it acts on both variables
        self.rhs_exp_args['exp_nonstiff'] = [0] 
        self.diagonal_nonstiff['exp_nonstiff'] = False
        self.diagonal_stiff['exp_nonstiff'] = False

        # here we consider the three terms
        self.rhs_nonstiff['exp_stiff_nonstiff'] = [1.0+self.uh.sub(0)**2*self.uh.sub(1)+5.*ufl.exp(-((self.x[0]-0.3)**2+(self.x[1]-0.6)**2)/0.005), 3.4*self.uh.sub(0)-self.uh.sub(0)**2*self.uh.sub(1)]
        self.rhs_stiff['exp_stiff_nonstiff'] = [None,None]      
        self.lmbda['exp_stiff_nonstiff'] = [-4.4,None]  
        self.yinf['exp_stiff_nonstiff'] = [0.,None]
        self.rhs_nonstiff_args['exp_stiff_nonstiff'] = [0,1] 
        self.rhs_stiff_args['exp_stiff_nonstiff'] = [0,1]  # do not forget the laplacian!! it acts on both variables
        self.rhs_exp_args['exp_stiff_nonstiff'] = [0] 
        self.diagonal_nonstiff['exp_stiff_nonstiff'] = False
        self.diagonal_stiff['exp_stiff_nonstiff'] = False

    @property
    def u0_expr(self):        
        return self.u0
    
class Monodomain(parabolic_system_problem):
    def __init__(self,dim,n_elems):
        dom_size=[[0.,0.,0.],[20.,7.,3.]]
        super(Monodomain,self).__init__(dim,n_elems,dom_size)

        self.know_exact = False
        self.cte_Dirichlet = True 
        self.rhs_or_N_bnd_dep_t = True
        self.bnd_cond = 'N' 

        # self.ionic_model = ionicmodels.HodgkinHuxley() # Available: HodgkinHuxley, RogersMcCulloch
        self.ionic_model = ionicmodels_myokit.TenTusscher2006_epi() # Available: HodgkinHuxley, Courtemanche1998, Fox2002, TenTusscher2006_epi
        self.size = self.ionic_model.size
        self.sp_ind = [0]
        self.diff = [0] # defined later

        self.t0 = 0.
        self.Tend = 60. # ms

        n_pts = 10
        # a = np.reshape(np.array(dom_size[0]),(1,3))
        a = np.array([[1.5,1.5,1.5]])
        b = np.reshape(np.array(dom_size[1]),(1,3))
        x = np.reshape(np.linspace(0.,1.,n_pts),(n_pts,1))
        self.eval_points = a+(b-a)*x
        self.eval_points = np.zeros((n_pts,3))
        for i in range(n_pts):
            self.eval_points[i,:] = np.reshape(a+(b-a)*x[i],(3,))
            
        if dim==1:
            self.eval_points[:,1:] = 0
        elif dim==2:
            self.eval_points[:,2] = 0
            
        self.chi = 140 # mm^-1
        self.Cm = 0.01 # uF/mm^2
        self.si_l = 0.17 # mS/mm
        self.se_l = 0.62 # mS/mm
        self.si_t = 0.019 # mS/mm
        self.se_t = 0.24 # mS/mm
        self.sigma_l = self.si_l*self.se_l/(self.si_l+self.se_l)
        self.sigma_t = self.si_t*self.se_t/(self.si_t+self.se_t)
        self.diff_l = self.sigma_l/self.chi/self.Cm
        self.diff_t = self.sigma_t/self.chi/self.Cm  

        self.scale_Iion = 0.01 # used to convert currents in uA/cm^2 to uA/mm^2

        self.stim_dur = 2. # ms
        self.stim_intensity = 35.7143 # in uA/cm^2, it is converted later in uA/mm^2 using self.scale_Iion
        # self.first_stim = 1.
        # self.end_stim = 16.
        # self.stim_interval = 5.        
                
    def define_domain_dependent_variables(self,domain,V,dtype_u):
        super().define_domain_dependent_variables(domain,V,dtype_u)            
        self.ionic_model.set_domain(self.domain)
        
        if self.dim==1:
            self.diff[0] = self.diff_l
        elif self.dim==2:
            fiber = np.array([[1.],[0.]])
            id = np.identity(2,dtype=fiber.dtype)
            self.diff[0] = fem.Constant(self.domain,self.diff_t*id+self.diff_l*fiber*fiber.T)            
        else:
            fiber = np.array([[1.],[0.],[0.]])
            id = np.identity(3,dtype=fiber.dtype)
            self.diff[0] = fem.Constant(self.domain,self.diff_t*id+self.diff_l*fiber*fiber.T)
        
        self.zero_fun = fem.Constant(self.domain,0.)
        self.one_fun = fem.Constant(self.domain,1.)
        self.g = [self.zero_fun]+[None]*(self.size-1)     
        
        self.rhs = self.ionic_model.f(self.uh)
        self.rhs[0] += self.Istim()
        if abs(self.scale_Iion/self.Cm-1.)>1e-10:
            self.rhs[0] *= self.scale_Iion/self.Cm   

        # Here we define different splittings of the rhs into stiff, nonstiff and exponential terms
        self.rhs_stiff = dict()
        self.rhs_nonstiff = dict()
        self.lmbda = dict()
        self.yinf = dict()
        self.rhs_nonstiff_args = dict()
        self.rhs_stiff_args = dict()
        self.rhs_exp_args = dict()
        self.diagonal_stiff = dict()
        self.diagonal_nonstiff = dict()

        # this is a splitting to be used in multirate explicit stabilized methods
        self.rhs_nonstiff['stiff_nonstiff'] = self.ionic_model.f_nonstiff(self.uh)
        if self.rhs_nonstiff['stiff_nonstiff'][0] is not None:
            self.rhs_nonstiff['stiff_nonstiff'][0] += self.Istim()
        else:
            self.rhs_nonstiff['stiff_nonstiff'][0] = self.Istim()
        if abs(self.scale_Iion/self.Cm-1.)>1e-10:
            self.rhs_nonstiff['stiff_nonstiff'][0] *= self.scale_Iion/self.Cm         
        self.rhs_nonstiff_args['stiff_nonstiff'] = self.ionic_model.f_nonstiff_args 
        if 0 not in self.rhs_nonstiff_args['stiff_nonstiff']:
            self.rhs_nonstiff_args['stiff_nonstiff'] = [0]+self.rhs_nonstiff_args['stiff_nonstiff']
        self.diagonal_nonstiff['stiff_nonstiff'] = True # f_nonstiff acts element wise, hence Jacobian is block diagonal

        self.rhs_stiff['stiff_nonstiff'] = self.ionic_model.f_stiff(self.uh)    
        if self.rhs_stiff['stiff_nonstiff'][0] is not None and abs(self.scale_Iion/self.Cm-1.)>1e-10:    
            self.rhs_stiff['stiff_nonstiff'][0] *= self.scale_Iion/self.Cm   
        self.rhs_stiff_args['stiff_nonstiff'] = self.ionic_model.f_stiff_args
        if 0 not in self.rhs_stiff_args['stiff_nonstiff']:
            self.rhs_stiff_args['stiff_nonstiff'] = [0]+self.rhs_stiff_args['stiff_nonstiff']
        self.diagonal_stiff['stiff_nonstiff'] = False # Laplacian is not element-wise operator
        self.lmbda['stiff_nonstiff'] = [None]*self.size
        self.yinf['stiff_nonstiff'] = [None]*self.size
        self.rhs_exp_args['stiff_nonstiff'] = []

        # this splitting is to be used in Rush-Larsen methods
        self.rhs_nonstiff['exp_nonstiff'] = self.ionic_model.f_expl(self.uh)
        if self.rhs_nonstiff['exp_nonstiff'][0] is not None:
            self.rhs_nonstiff['exp_nonstiff'][0] += self.Istim()
        else:
            self.rhs_nonstiff['exp_nonstiff'][0] = self.Istim()
        if abs(self.scale_Iion/self.Cm-1.)>1e-10:
            self.rhs_nonstiff['exp_nonstiff'][0] *= self.scale_Iion/self.Cm  
        self.rhs_nonstiff_args['exp_nonstiff'] = self.ionic_model.f_expl_args 
        if 0 not in self.rhs_nonstiff_args['exp_nonstiff']:
            self.rhs_nonstiff_args['exp_nonstiff'] = [0]+self.rhs_nonstiff_args['exp_nonstiff']
        self.diagonal_nonstiff['exp_nonstiff'] = True

        self.rhs_stiff['exp_nonstiff'] = [None]*self.size
        self.rhs_stiff_args['exp_nonstiff'] = [0]
        self.diagonal_stiff['exp_nonstiff'] = False
        self.lmbda['exp_nonstiff'] = [None]*self.size
        self.yinf['exp_nonstiff'] = [None]*self.size
        self.rhs_exp_args['exp_nonstiff'] = []
        yinf, tau = self.ionic_model.u_exp_coeffs(self.uh)
        for i in range(self.size):
            if yinf[i] is not None:
                self.lmbda['exp_nonstiff'][i] = -1./tau[i]
                self.yinf['exp_nonstiff'][i] = yinf[i]
                self.rhs_exp_args['exp_nonstiff'].append(i)

        # this splitting is the same as above, but is used for methods with exponential Runge-Kutta as underlying collocation method
        self.rhs_nonstiff['exp_nonstiff_dir_sum'] = self.rhs_nonstiff['exp_nonstiff']
        self.rhs_nonstiff_args['exp_nonstiff_dir_sum'] = self.rhs_nonstiff_args['exp_nonstiff']
        self.diagonal_nonstiff['exp_nonstiff_dir_sum'] = self.diagonal_nonstiff['exp_nonstiff']
        self.rhs_stiff['exp_nonstiff_dir_sum'] = self.rhs_stiff['exp_nonstiff']
        self.rhs_stiff_args['exp_nonstiff_dir_sum'] = self.rhs_stiff_args['exp_nonstiff']
        self.diagonal_stiff['exp_nonstiff_dir_sum'] = self.diagonal_stiff['exp_nonstiff']
        self.lmbda['exp_nonstiff_dir_sum'] = self.lmbda['exp_nonstiff']
        self.yinf['exp_nonstiff_dir_sum'] = self.yinf['exp_nonstiff']
        self.rhs_exp_args['exp_nonstiff_dir_sum'] = self.rhs_exp_args['exp_nonstiff']

        # This is a splitting similar to the one for stabilized methods but where the rhs_stiff variables are
        # integrated exponentially. The difference with respect to Rush-Larsen is that only truly stiff 
        # variables are integrated exponentially (usually only one), while slightly stiff variables are 
        # still integrated via explicit stabilized methods. 
        self.rhs_nonstiff['exp_stiff_nonstiff'] = self.rhs_nonstiff['stiff_nonstiff']
        self.rhs_nonstiff_args['exp_stiff_nonstiff'] = self.rhs_nonstiff_args['stiff_nonstiff']
        self.diagonal_nonstiff['exp_stiff_nonstiff'] = True
        self.rhs_stiff['exp_stiff_nonstiff'] = [None]*self.size
        self.rhs_stiff_args['exp_stiff_nonstiff'] = [0]
        self.diagonal_stiff['exp_stiff_nonstiff'] = False
        self.lmbda['exp_stiff_nonstiff'] = [None]*self.size
        self.yinf['exp_stiff_nonstiff'] = [None]*self.size
        self.rhs_exp_args['exp_stiff_nonstiff'] = []
        yinf, tau = self.ionic_model.u_stiff_coeffs(self.uh)
        for i in range(self.size):
            if yinf[i] is not None:
                self.lmbda['exp_stiff_nonstiff'][i] = -1./tau[i]
                self.yinf['exp_stiff_nonstiff'][i] = yinf[i]
                self.rhs_exp_args['exp_stiff_nonstiff'].append(i)

        # this splitting is the same as above, but is used for methods with exponential Runge-Kutta as underlying collocation method
        self.rhs_nonstiff['exp_stiff_nonstiff_dir_sum'] = self.rhs_nonstiff['exp_stiff_nonstiff']
        self.rhs_nonstiff_args['exp_stiff_nonstiff_dir_sum'] = self.rhs_nonstiff_args['exp_stiff_nonstiff']
        self.diagonal_nonstiff['exp_stiff_nonstiff_dir_sum'] = self.diagonal_nonstiff['exp_stiff_nonstiff']
        self.rhs_stiff['exp_stiff_nonstiff_dir_sum'] = self.rhs_stiff['exp_stiff_nonstiff']
        self.rhs_stiff_args['exp_stiff_nonstiff_dir_sum'] = self.rhs_stiff_args['exp_stiff_nonstiff']
        self.diagonal_stiff['exp_stiff_nonstiff_dir_sum'] = self.diagonal_stiff['exp_stiff_nonstiff']
        self.lmbda['exp_stiff_nonstiff_dir_sum'] = self.lmbda['exp_stiff_nonstiff']
        self.yinf['exp_stiff_nonstiff_dir_sum'] = self.yinf['exp_stiff_nonstiff']
        self.rhs_exp_args['exp_stiff_nonstiff_dir_sum'] = self.rhs_exp_args['exp_stiff_nonstiff']

        self.u0 = [fem.Constant(self.domain,y0) for y0 in self.ionic_model.initial_values()]        
        V0_bnd = -1.5
        V0 = 27
        if self.dim ==1:
            V0_expr = ufl.conditional(ufl.le(self.x[0], V0_bnd), V0, self.u0[0])
        elif self.dim==2:    
            V0_expr = ufl.conditional(ufl.And(ufl.le(self.x[0], V0_bnd),ufl.le(self.x[1], V0_bnd)), V0, self.u0[0])
        else:
            V0_expr = ufl.conditional(ufl.And(ufl.And(ufl.le(self.x[0], V0_bnd),ufl.le(self.x[1], V0_bnd)),ufl.le(self.x[2], V0_bnd)), V0, self.u0[0])           
        self.u0[0] = V0_expr

    @property
    def u0_expr(self):                
        return self.u0

    def Istim(self):        
        stim_bnd = 1.5
        if self.dim ==1:
            return ufl.conditional(ufl.And(ufl.lt(self.t,self.stim_dur),ufl.le(self.x[0], stim_bnd)), self.stim_intensity, self.zero_fun)
        elif self.dim==2:    
            return ufl.conditional(ufl.And(ufl.lt(self.t,self.stim_dur),ufl.And(ufl.le(self.x[0], stim_bnd),ufl.le(self.x[1], stim_bnd))), self.stim_intensity, self.zero_fun)
        else:
            return ufl.conditional(ufl.And(ufl.lt(self.t,self.stim_dur),ufl.And(ufl.And(ufl.le(self.x[0], stim_bnd),ufl.le(self.x[1], stim_bnd)),ufl.le(self.x[2], stim_bnd))), self.stim_intensity, self.zero_fun)
        
    def rho_nonstiff(self,y,t,fy=None):
        if isinstance(self.ionic_model,ionicmodels_myokit.TenTusscher2006_epi):
            return 6.5
        elif isinstance(self.ionic_model,ionicmodels_myokit.Courtemanche1998):
            return 7.5
        elif isinstance(self.ionic_model,ionicmodels_myokit.HodgkinHuxley):
            return 40.
        # elif isinstance(self.ionic_model,ionicmodels.HodgkinHuxley):
        #     return 40.
        # elif isinstance(self.ionic_model,ionicmodels.RogersMcCulloch):
        #     return
        else:
            raise Exception('rho_nonstiff not implemented for this ionic model.')