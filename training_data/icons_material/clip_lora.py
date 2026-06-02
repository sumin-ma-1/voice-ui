"""Low-rank adapters for OpenAI CLIP ViT-B/32 linear layers."""

from __future__ import annotations

import torch
import torch.nn as nn

DEFAULT_LORA_SUFFIXES = ("attn.out_proj", "mlp.c_fc", "mlp.c_proj")


class LoRALinear(nn.Module):
    """Wraps nn.Linear with trainable low-rank delta: W'x = Wx + scale * B(Ax)."""

    def __init__(self, linear: nn.Linear, *, r: int, alpha: float) -> None:
        super().__init__()
        if r <= 0:
            raise ValueError("LoRA rank must be positive")
        self.linear = linear
        self.r = r
        self.scaling = alpha / r
        in_features = linear.in_features
        out_features = linear.out_features
        # Make LoRA params match the base Linear device/dtype.
        device = linear.weight.device
        dtype = linear.weight.dtype
        self.lora_A = nn.Parameter(torch.zeros(r, in_features, device=device, dtype=dtype))
        self.lora_B = nn.Parameter(torch.zeros(out_features, r, device=device, dtype=dtype))
        nn.init.kaiming_uniform_(self.lora_A, a=5**0.5)
        nn.init.zeros_(self.lora_B)
        for p in self.linear.parameters():
            p.requires_grad = False

    @property
    def weight(self) -> torch.Tensor:
        # CLIP MultiheadAttention reads out_proj.weight directly.
        return self.linear.weight

    @property
    def bias(self) -> torch.Tensor | None:
        return self.linear.bias

    @property
    def in_features(self) -> int:
        return self.linear.in_features

    @property
    def out_features(self) -> int:
        return self.linear.out_features

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        base = self.linear(x)
        lora = (x @ self.lora_A.T @ self.lora_B.T) * self.scaling
        return base + lora

    def merge_into_base(self) -> nn.Linear:
        with torch.no_grad():
            delta = (self.lora_B @ self.lora_A) * self.scaling
            self.linear.weight.add_(delta)
        return self.linear


def inject_clip_lora(
    model: nn.Module,
    *,
    r: int = 8,
    alpha: float = 16.0,
    target_suffixes: tuple[str, ...] = DEFAULT_LORA_SUFFIXES,
    visual_only: bool = False,
    text_only: bool = False,
) -> list[str]:
    """Replace matching Linear layers with LoRALinear. Returns dotted module names."""
    if visual_only and text_only:
        raise ValueError("visual_only and text_only cannot both be set")
    replaced: list[str] = []
    for name, module in list(model.named_modules()):
        if visual_only and not name.startswith("visual."):
            continue
        if text_only and not name.startswith("transformer."):
            continue
        if not any(name.endswith(suffix) for suffix in target_suffixes):
            continue
        if not isinstance(module, nn.Linear):
            continue
        parent_name, child_name = name.rsplit(".", 1)
        parent = model.get_submodule(parent_name)
        setattr(parent, child_name, LoRALinear(module, r=r, alpha=alpha))
        replaced.append(name)
    return replaced


def lora_trainable_parameters(model: nn.Module) -> list[nn.Parameter]:
    params: list[nn.Parameter] = []
    for module in model.modules():
        if isinstance(module, LoRALinear):
            params.extend([module.lora_A, module.lora_B])
    return params


def merge_and_unwrap_lora(model: nn.Module) -> int:
    """Merge LoRA deltas into base Linear weights and restore plain nn.Linear modules."""
    merged = 0
    for name, module in list(model.named_modules()):
        if not isinstance(module, LoRALinear):
            continue
        linear = module.merge_into_base()
        parent_name, child_name = name.rsplit(".", 1)
        parent = model.get_submodule(parent_name)
        setattr(parent, child_name, linear)
        merged += 1
    return merged


def count_lora_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in lora_trainable_parameters(model))
