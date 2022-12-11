# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/05_diffusion.ipynb.

# %% auto 0
__all__ = ['diff_name2kls', 'MinimalDiffusion']

# %% ../nbs/05_diffusion.ipynb 2
from PIL import Image
import torch
from torch import nn
from tqdm    import tqdm
from transformers import CLIPTextModel, CLIPTokenizer
import diffusers
from diffusers import AutoencoderKL, UNet2DConditionModel
from diffusers import LMSDiscreteScheduler, DDIMScheduler, EulerDiscreteScheduler, DPMSolverMultistepScheduler, EulerAncestralDiscreteScheduler
from .kdiff import *

# %% ../nbs/05_diffusion.ipynb 3
'''Map from string name to `diffusers` class.'''
diff_name2kls = {
    'pndm' : diffusers.schedulers.scheduling_pndm.PNDMScheduler, 
    'ddpm' : diffusers.schedulers.scheduling_ddpm.DDPMScheduler, 
    'ddim' : diffusers.schedulers.scheduling_ddim.DDIMScheduler, 
    'euler_ancestral' : diffusers.schedulers.scheduling_euler_ancestral_discrete.EulerAncestralDiscreteScheduler, 
    'heun' : diffusers.schedulers.scheduling_heun_discrete.HeunDiscreteScheduler, 
    'euler' : diffusers.schedulers.scheduling_euler_discrete.EulerDiscreteScheduler, 
    'lms' : diffusers.schedulers.scheduling_lms_discrete.LMSDiscreteScheduler, 
    'dpm_multi' : diffusers.schedulers.scheduling_dpmsolver_multistep.DPMSolverMultistepScheduler, 
    'dpm_single' : diffusers.schedulers.scheduling_dpmsolver_singlestep.DPMSolverSinglestepScheduler, 
    'kdpm2': diffusers.schedulers.scheduling_k_dpm_2_discrete.KDPM2DiscreteScheduler,
    'kdpm2_ancestral': diffusers.schedulers.scheduling_k_dpm_2_ancestral_discrete.KDPM2AncestralDiscreteScheduler,
}

# %% ../nbs/05_diffusion.ipynb 4
class MinimalDiffusion:
    """Loads a Stable Diffusion pipeline.
    
    The goal is to have more control of the image generation loop. 
    This class loads the following individual pieces:
        - Tokenizer
        - Text encoder
        - VAE
        - U-Net
        - Sampler
        
    The `self.generate` function uses these pieces to run a Diffusion image generation loop.
    
    This class can be subclasses and any of its methods overriden to gain even more control over the Diffusion pipeline. 
    """
    def __init__(self, model_name, device, dtype, revision,
                 better_vae='', unet_attn_slice=True, schedule_kwargs={}):
        self.model_name = model_name
        self.device = device
        self.dtype = dtype
        self.revision = revision
        self.generator = None 
        self.better_vae = better_vae
        self.unet_attn_slice = unet_attn_slice
        # group the sampler kwargs
        self.schedule_kwargs = schedule_kwargs
        
        
    def load(self):
        """Loads and returns the individual pieces in a Diffusion pipeline.        
        """
        # load the pieces
        self.load_text_pieces()
        self.load_vae()
        self.load_unet()
        self.load_scheduler()
        # put them on the device
        self.to_device()
    
    def load_text_pieces(self):
        """Creates the tokenizer and text encoder.
        """
        tokenizer = CLIPTokenizer.from_pretrained(
            self.model_name,
            subfolder="tokenizer",
            torch_dtype=self.dtype)
        text_encoder = CLIPTextModel.from_pretrained(
            self.model_name,
            subfolder="text_encoder",
            torch_dtype=self.dtype)
        self.tokenizer = tokenizer
        self.text_encoder = text_encoder
    
    
    def load_vae(self):
        """Loads the Variational Auto-Encoder.
        
        Optionally loads an improved `better_vae` from the stability.ai team.
            It can be either the `ema` or `mse` VAE.
        """
        # optionally use a VAE from stability that was trained for longer 
        if self.better_vae:
            assert self.better_vae in ('ema', 'mse')
            print(f'Using the improved VAE "{self.better_vae}" from stabiliy.ai')
            vae = AutoencoderKL.from_pretrained(
                f"stabilityai/sd-vae-ft-{self.better_vae}",
                revision=self.revision,
                torch_dtype=self.dtype)
        else:
            vae = AutoencoderKL.from_pretrained(self.model_name, subfolder='vae',
                                                torch_dtype=self.dtype)
        self.vae = vae

        
    def load_unet(self):
        """Loads the U-Net.
        
        Optionally uses attention slicing to fit on smaller GPU cards.
        """
        unet = UNet2DConditionModel.from_pretrained(
            self.model_name,
            subfolder="unet",
            #revision=self.revision,
            torch_dtype=self.dtype)
        # optionally enable unet attention slicing
        if self.unet_attn_slice:
            print('Enabling default unet attention slicing.')
            if isinstance(unet.config.attention_head_dim, int):
                # half the attention head size is usually a good trade-off between
                # speed and memory
                slice_size = unet.config.attention_head_dim // 2
            else:
                # if `attention_head_dim` is a list, take the smallest head size
                slice_size = min(unet.config.attention_head_dim)
            unet.set_attention_slice(slice_size)
        self.unet = unet
        
                
    def load_scheduler(self):
        """Loads the scheduler.
        """
        # parse out the name of the scheduler
        scheduler_name = self.schedule_kwargs.get('scheduler_kls')
        self.use_k_diffusion = scheduler_name.startswith('k_')
        
        # load the k-diffusion class
        if self.use_k_diffusion:
            SamplerCls = SAMPLER_LOOKUP[scheduler_name]
            self.sampler = SamplerCls(self.unet, self.model_name)
            print(f'Using k-diffusion sampler: {self.sampler}')
        
        # use the huggingface diffusers class
        else:
            sched_kls = diff_name2kls[scheduler_name]
            self.scheduler = sched_kls.from_pretrained(self.model_name, subfolder="scheduler")
            print(f'Using diffusers scheduler: {self.scheduler}')


    def generate(
        self,
        prompt,
        dynamic_cfg=None,
        width=512,
        height=512,
        num_steps=50,
        use_karras_sigmas=False,
        **kwargs
    ):
        """Main image generation loop.
        """

        # prepare the text embeddings
        text = self.encode_text(prompt)
        neg_prompt = kwargs.get('negative_prompt', '')
        if neg_prompt:
            print(f'Using negative prompt: {neg_prompt}')
        else:
            print(f'No negative prompt, using empty unconditional input')
        uncond = self.encode_text(neg_prompt)
        
        # start from shared, initial latents
        if getattr(self, 'init_latents', None) is None:
            self.init_latents = self.get_initial_latents(height, width)
        latents = self.init_latents.clone().to(self.unet.device)

        # store reference to dynamic guider
        self.dynamic_cfg = dynamic_cfg
        
        # use the k-diffusion library
        if self.use_k_diffusion:
            latents = self.k_sampling_loop(num_steps, text, uncond, latents)
        
        # use the diffusers scheduler loop
        else:
            # set the number of scheduler steps
            self.scheduler.set_timesteps(num_steps, device=self.unet.device)
            # for dynamic guidance, use the number of total scheduler steps
            self.dynamic_cfg.set_timesteps(len(self.scheduler.timesteps))
            # prepare the conditional and unconditional inputs
            text_emb = torch.cat([uncond, text]).type(self.unet.dtype)
            # scale the initial input latents
            latents = latents * self.scheduler.init_noise_sigma
            # run the diffusion process
            for i,ts in enumerate(tqdm(self.scheduler.timesteps)):
                latents = self.diffuse_step(latents, text_emb, ts, i)

        # decode the final latents and return the generated image
        image = self.image_from_latents(latents)
        return image    


    def diffuse_step(self, latents, text_emb, ts, idx):
        """Runs a single diffusion step.
        """
        inp = self.scheduler.scale_model_input(torch.cat([latents] * 2), ts)
        with torch.no_grad(): 
            tf = ts
            if torch.has_mps:
                tf = ts.type(torch.float32)
            preds = self.unet(inp, tf, encoder_hidden_states=text_emb)
            u, t  = preds.sample.chunk(2)
        
        # run classifier-free guidance
        pred = self.dynamic_cfg.guide(u, t, idx)
        
        # update and return the latents
        latents = self.scheduler.step(pred, ts, latents).prev_sample
        return latents
    
    
    def k_sampling_loop(self, num_steps, text, uncond, latents):
        '''Run the k-diffusion sampling loop.
        '''
        # move wrapped sigmas and log-sigmas to device
        self.sampler.cv_denoiser.sigmas = self.sampler.cv_denoiser.sigmas.to(latents.device)
        self.sampler.cv_denoiser.log_sigmas = self.sampler.cv_denoiser.log_sigmas.to(latents.device)

        # sample with k_diffusion
        latents = self.sampler.sample(
            num_steps=num_steps,
            initial_latent=latents,
            positive_conditioning=text,
            neutral_conditioning=uncond,
            t_start=None,#t_enc,
            mask=None,#mask,
            orig_latent=None,#init_latent,
            shape=latents.shape,
            batch_size=1,
            dynamic_cfg=self.dynamic_cfg,
            use_karras_sigmas=self.schedule_kwargs.get('use_karras_sigmas', False),
        )
        return latents
    

    def encode_text(self, prompts, maxlen=None):
        """Extracts text embeddings from the given `prompts`.
        """
        maxlen = maxlen or self.tokenizer.model_max_length
        inp = self.tokenizer(prompts, padding="max_length", max_length=maxlen, 
                             truncation=True, return_tensors="pt")
        inp_ids = inp.input_ids.to(self.device)
        return self.text_encoder(inp_ids)[0]

    
    def to_device(self, device=None):
        """Places to pipeline pieces on the given device
        
        Note: assumes we keep Scheduler and Tokenizer on the cpu.
        """
        device = device or self.device
        for m in (self.text_encoder, self.vae, self.unet):
            m.to(device)
    
    
    def set_initial_latents(self, latents):
        """Sets the given `latents` as the initial noise latents.
        """
        self.init_latents = latents
        
        
    def get_initial_latents(self, height, width):
        """Returns an initial set of latents.
        """
        return torch.randn((1, self.unet.in_channels, height//8, width//8),
                           dtype=self.dtype, generator=self.generator)
    
    
    def image_from_latents(self, latents):
        """Scales diffusion `latents` and turns them into a PIL Image.
        """
        # scale and decode the latents
        latents = 1 / 0.18215 * latents
        with torch.no_grad():
            data = self.vae.decode(latents.type(self.vae.dtype)).sample[0]
        # Create PIL image
        data = (data / 2 + 0.5).clamp(0, 1)
        data = data.cpu().permute(1, 2, 0).float().numpy()
        data = (data * 255).round().astype("uint8")
        image = Image.fromarray(data)
        return image
