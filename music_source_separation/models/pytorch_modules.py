from typing import NoReturn, List

import numpy as np
import torch.nn as nn
import torch
import torch.nn.functional as F

from torchlibrosa.stft import magphase


def init_embedding(layer: nn.Module) -> NoReturn:
    r"""Initialize a Linear or Convolutional layer."""
    nn.init.uniform_(layer.weight, -1.0, 1.0)

    if hasattr(layer, 'bias'):
        if layer.bias is not None:
            layer.bias.data.fill_(0.0)


def init_layer(layer: nn.Module) -> NoReturn:
    r"""Initialize a Linear or Convolutional layer."""
    nn.init.xavier_uniform_(layer.weight)

    if hasattr(layer, "bias"):
        if layer.bias is not None:
            layer.bias.data.fill_(0.0)


def init_bn(bn: nn.Module) -> NoReturn:
    r"""Initialize a Batchnorm layer."""
    bn.bias.data.fill_(0.0)
    bn.weight.data.fill_(1.0)
    bn.running_mean.data.fill_(0.0)
    bn.running_var.data.fill_(1.0)


def act(x: torch.Tensor, activation: str) -> torch.Tensor:
    if activation == "relu":
        return F.relu_(x)

    elif activation == "leaky_relu":
        return F.leaky_relu_(x, negative_slope=0.01)

    elif activation == "swish":
        return x * torch.sigmoid(x)

    else:
        raise Exception("Incorrect activation!")


class Base:
    def __init__(self):
        r"""Base function for extracting spectrogram, cos, and sin, etc."""
        pass

    def spectrogram(self, input: torch.Tensor, eps: float = 0.0) -> torch.Tensor:
        r"""Calculate spectrogram.

        Args:
            input: (batch_size, segments_num)
            eps: float

        Returns:
            spectrogram: (batch_size, time_steps, freq_bins)
        """
        (real, imag) = self.stft(input)
        return torch.clamp(real ** 2 + imag ** 2, eps, np.inf) ** 0.5

    def spectrogram_phase(
        self, input: torch.Tensor, eps: float = 0.0
    ) -> List[torch.Tensor]:
        r"""Calculate the magnitude, cos, and sin of the STFT of input.

        Args:
            input: (batch_size, segments_num)
            eps: float

        Returns:
            mag: (batch_size, time_steps, freq_bins)
            cos: (batch_size, time_steps, freq_bins)
            sin: (batch_size, time_steps, freq_bins)
        """
        (real, imag) = self.stft(input)
        mag = torch.clamp(real ** 2 + imag ** 2, eps, np.inf) ** 0.5
        cos = real / mag
        sin = imag / mag
        return mag, cos, sin

    def wav_to_spectrogram_phase(
        self, input: torch.Tensor, eps: float = 1e-10
    ) -> List[torch.Tensor]:
        r"""Convert waveforms to magnitude, cos, and sin of STFT.

        Args:
            input: (batch_size, channels_num, segment_samples)
            eps: float

        Outputs:
            mag: (batch_size, channels_num, time_steps, freq_bins)
            cos: (batch_size, channels_num, time_steps, freq_bins)
            sin: (batch_size, channels_num, time_steps, freq_bins)
        """
        batch_size, channels_num, segment_samples = input.shape

        # Reshape input with shapes of (n, segments_num) to meet the
        # requirements of the stft function.
        x = input.reshape(batch_size * channels_num, segment_samples)

        mag, cos, sin = self.spectrogram_phase(x, eps=eps)
        # mag, cos, sin: (batch_size * channels_num, 1, time_steps, freq_bins)

        _, _, time_steps, freq_bins = mag.shape
        mag = mag.reshape(batch_size, channels_num, time_steps, freq_bins)
        cos = cos.reshape(batch_size, channels_num, time_steps, freq_bins)
        sin = sin.reshape(batch_size, channels_num, time_steps, freq_bins)

        return mag, cos, sin

    '''
    def spectrogram_to_wav(self, input, spectrogram, length=None):
        """Spectrogram to waveform.

        Args:
          input: (batch_size, segment_samples, channels_num)
          spectrogram: (batch_size, channels_num, time_steps, freq_bins)

        Outputs:
          output: (batch_size, channels_num, segment_samples)
        """
        channels_num = input.shape[1]
        wav_list = []
        for channel in range(channels_num):
            (real, imag) = self.stft(input[:, channel, :])
            (_, cos, sin) = magphase(real, imag)
            wav_list.append(
                self.istft(
                    spectrogram[:, channel : channel + 1, :, :] * cos,
                    spectrogram[:, channel : channel + 1, :, :] * sin,
                    length,
                )
            )

        output = torch.stack(wav_list, dim=1)
        return output
    '''


class Subband:
    def __init__(self, subbands_num: int):
        r"""Analysis and synthesis spectrogram into subbands [1].

        [1] Liu, Haohe, et al. "Channel-wise subband input for better voice and
        accompaniment separation on high resolution music." arXiv preprint arXiv:2008.05216 (2020).

        Args:
            subbands_num: int, e.g., 4
        """
        self.subbands_num = subbands_num

    def analysis(self, x: torch.Tensor) -> torch.Tensor:
        r"""Analysis time-frequency representation into subbands. Stack the
        subbands along the channel axis.

        Args:
            x: (batch_size, channels_num, time_steps, freq_bins)

        Returns:
            output: (batch_size, channels_num * subbands_num, time_steps, freq_bins // subbands_num)
        """
        batch_size, channels_num, time_steps, freq_bins = x.shape

        x = x.reshape(
            batch_size,
            channels_num,
            time_steps,
            self.subbands_num,
            freq_bins // self.subbands_num,
        )
        # x: (batch_size, channels_num, time_steps, subbands_num, freq_bins // subbands_num)

        x = x.transpose(2, 3)

        output = x.reshape(
            batch_size,
            channels_num * self.subbands_num,
            time_steps,
            freq_bins // self.subbands_num,
        )
        # output: (batch_size, channels_num * subbands_num, time_steps, freq_bins // subbands_num)

        return output

    def synthesis(self, x: torch.Tensor) -> torch.Tensor:
        r"""Synthesis subband time-frequency representations into original
        time-frequency representation.

        Args:
            x: (batch_size, channels_num * subbands_num, time_steps, freq_bins // subbands_num)

        Returns:
            output: (batch_size, channels_num, time_steps, freq_bins)
        """
        batch_size, subband_channels_num, time_steps, subband_freq_bins = x.shape

        channels_num = subband_channels_num // self.subbands_num
        freq_bins = subband_freq_bins * self.subbands_num

        x = x.reshape(
            batch_size,
            channels_num,
            self.subbands_num,
            time_steps,
            freq_bins // self.subbands_num,
        )
        # x: (batch_size, channels_num, subbands_num, time_steps, freq_bins // subbands_num)

        x = x.transpose(2, 3)
        # x: (batch_size, channels_num, time_steps, subbands_num, freq_bins // subbands_num)

        output = x.reshape(batch_size, channels_num, time_steps, freq_bins)
        # x: (batch_size, channels_num, time_steps, freq_bins)

        return output
