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
    """Baseline Classifier-free Guidance for Diffusion.
    """
    name = "CFGuidance"
    def __init__(self):
        # variables for the unconditioned and conditioned latents
        self.u, self.t = None, None
        # variable for the guidance update and final predictions
        self.diff, self.pred = None, None

    def apply_cfg(self, guidance_scale):
        pred = self.u + guidance_scale * (self.diff)
        self.pred = pred

    def pre_proc (self): pass
    def post_proc(self): pass

    def set_u(self, u): self.u = u
    def set_t(self, t): self.t = t
    def set_latents(self, u, t):
        self.u, self.t = u, t

    def compute_update(self):
        self.diff = self.t - self.u

    def set_pred(self, pred): self.pred = pred
    def get_pred(self): return self.pred
    
    
class PredNormGuidance(GuidanceTfm):
    """Scales the noise prediction by its overall norm.
    """
    name = "BaseNormGuidance"
    def post_proc(self):
        self.pred = self.pred * (torch.linalg.norm(self.u) / torch.linalg.norm(self.pred))
        
        
class TNormGuidance(GuidanceTfm):
    """Scales the latent mix of `t - u`.

    Note: Roughly equivalent to the GuidedTTS Norm
        Reference: https://arxiv.org/pdf/2205.15370.pdf
    """
    name = "TNormGuidance"
    def pre_proc(self):
        self.diff = (self.diff / torch.linalg.norm(self.diff)) * torch.linalg.norm(self.u)
        
        
class FullNormGuidance(TNormGuidance, PredNormGuidance):
    "Applies both Prediction and T-Norm on the noise prediction."
    name = "FullNormGuidance"


'''Map from string name to guidance normalization class.
'''
name2norm = {
    'no_norm': GuidanceTfm,
    'pred_norm': PredNormGuidance,
    't_norm': TNormGuidance,
    'full_norm': FullNormGuidance,
}

