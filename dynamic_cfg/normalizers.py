# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/02_normalizers.ipynb.

# %% auto 0
__all__ = ['name2norm', 'GuidanceTfm', 'PredNormGuidance', 'TNormGuidance', 'FullNormGuidance']

# %% ../nbs/02_normalizers.ipynb 3
'''Code for blog post:
    https://enzokro.dev/blog/posts/2022-11-15-guidance-expts-1
'''
import torch

# %% ../nbs/02_normalizers.ipynb 4
class GuidanceTfm:
    """Baseline Classifier-free Guidance for Difussion.
    """
    name = "CFGuidance"
    def __init__(self, has_preproc=False, has_postproc=False):
        self.has_preproc = has_preproc
        self.has_postproc = has_postproc
        self.u, self.t, self.pred = None, None, None

    def pre_proc (self): pass
    def post_proc(self): pass

    def set_latents(self, u, t):
        self.set_u(u), self.set_t(t)
    def set_u(self, u): self.u = u
    def set_t(self, t): self.t = t

    def compute_update(self):
        self.diff = self.t - self.u

    def set_pred(self, pred): self.pred = pred
    def get_pred(self): return self.pred
    
    
class PredNormGuidance(GuidanceTfm):
    """Scales the noise prediction by its overall norm.
    """
    name = "BaseNormGuidance"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, has_postproc=True, **kwargs)
    def post_proc(self):
        self.pred = self.pred * (torch.linalg.norm(self.u) / torch.linalg.norm(self.pred))
        
        
class TNormGuidance(GuidanceTfm):
    """Scales the latent mix of `t - u`
    """
    name = "TNormGuidance"
    def __init__(self, *args, **kwargs):
        super().__init__(has_preproc=True)
    def pre_proc(self):
        self.diff = self.diff / torch.linalg.norm(self.diff) * torch.linalg.norm(self.u)
        
        
class FullNormGuidance(GuidanceTfm):
    "Applies both Base and T-Norm on the noise prediction."
    name = "FullNormGuidance"
    def __init__(self, *args, **kwargs):
        super().__init__(has_postproc=True, has_preproc=True)
    def pre_proc(self):
        self.diff = self.diff / torch.linalg.norm(self.diff) * torch.linalg.norm(self.u)
    def post_proc(self):
        self.pred = self.pred * (torch.linalg.norm(self.u) / torch.linalg.norm(self.pred))


name2norm = {
    'no_norm': GuidanceTfm,
    'pred_norm': PredNormGuidance,
    't_norm': TNormGuidance,
    'full_norm': FullNormGuidance,
}

