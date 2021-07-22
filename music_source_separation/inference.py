from typing import Dict
import argparse
import time

import numpy as np
import torch
import torch.nn as nn
import librosa
import soundfile


class Separator:
    def __init__(
        self, model: nn.Module, segment_samples: int, batch_size: int, device: str
    ):
        r"""Separate to separate an audio clip into a target source.

        Args:
            model: nn.Module, trained model
            segment_samples: int, length of segments to be input to a model, e.g., 44100*30
            batch_size, int, e.g., 12
            device: str, e.g., 'cuda'
        """

        self.model = model
        self.segment_samples = segment_samples
        self.batch_size = batch_size
        self.device = device

    def separate(self, input_dict: Dict):
        r"""Separate an audio clip into a target source.

        Args:
            input_dict: dict, e.g., {
                waveform: (channels_num, audio_samples),
                ...,
            }

        Returns:
            sep_audio: (channels_num, audio_samples), separated audio
        """
        audio = input_dict['waveform']

        audio_samples = audio.shape[-1]

        # Pad the audio with zero in the end so that the length of audio can be
        # evenly divided by segment_samples.
        audio = self.pad_audio(audio)

        # Enframe long audio into segments.
        segments = self.enframe(audio, self.segment_samples)
        # (segments_num, channels_num, segment_samples)

        segments_input_dict = {'waveform': segments}

        if 'condition' in input_dict.keys():
            segments_num = len(segments)
            segments_input_dict['condition'] = np.tile(
                input_dict['condition'][None, :], (segments_num, 1)
            )

        # Separate in mini-batches.
        sep_segments = self._forward_in_mini_batches(
            self.model, segments_input_dict, self.batch_size
        )['wav']
        # (segments_num, channels_num, segment_samples)

        # Deframe segments into long audio.
        sep_audio = self.deframe(sep_segments)
        # (channels_num, padded_audio_samples)

        sep_audio = sep_audio[:, 0:audio_samples]
        # (channels_num, audio_samples)

        return sep_audio

    def pad_audio(self, audio):
        r"""Pad the audio with zero in the end so that the length of audio can
        be evenly divided by segment_samples.

        Args:
            audio: (channels_num, audio_samples)

        Returns:
            padded_audio: (channels_num, audio_samples)
        """
        channels_num, audio_samples = audio.shape

        # Number of segments
        segments_num = int(np.ceil(audio_samples / self.segment_samples))

        pad_samples = segments_num * self.segment_samples - audio_samples

        padded_audio = np.concatenate(
            (audio, np.zeros((channels_num, pad_samples))), axis=1
        )
        # (channels_num, padded_audio_samples)

        return padded_audio

    def enframe(self, audio, segment_samples):
        r"""Enframe long audio into segments.

        Args:
            audio: (channels_num, audio_samples)
            segment_samples: int

        Returns:
            segments: (segments_num, channels_num, segment_samples)
        """
        audio_samples = audio.shape[1]
        assert audio_samples % segment_samples == 0

        hop_samples = segment_samples // 2
        segments = []

        pointer = 0
        while pointer + segment_samples <= audio_samples:
            segments.append(audio[:, pointer : pointer + segment_samples])
            pointer += hop_samples

        segments = np.array(segments)

        return segments

    def deframe(self, segments):
        r"""Deframe segments into long audio.

        Args:
            segments: (segments_num, channels_num, segment_samples)

        Returns:
            output: (channels_num, audio_samples)
        """

        (segments_num, _, segment_samples) = segments.shape

        if segments_num == 1:
            return segments[0]

        assert self._is_integer(segment_samples * 0.25)
        assert self._is_integer(segment_samples * 0.75)

        output = []

        output.append(segments[0, :, 0 : int(segment_samples * 0.75)])

        for i in range(1, segments_num - 1):
            output.append(
                segments[
                    i, :, int(segment_samples * 0.25) : int(segment_samples * 0.75)
                ]
            )

        output.append(segments[-1, :, int(segment_samples * 0.25) :])

        output = np.concatenate(output, axis=-1)

        return output

    def _is_integer(self, x):
        if x - int(x) < 1e-10:
            return True
        else:
            return False

    def _forward_in_mini_batches(self, model, segments_input_dict, batch_size):
        r"""Forward data to model in mini-batch.

        Args:
            model: nn.Module
            segments_input_dict: dict, e.g., {
                'waveform': (segments_num, channels_num, segment_samples),
                ...,
            }
            batch_size: int

        Returns:
            output_dict: dict, e.g. {
                'waveform': (segments_num, channels_num, segment_samples),
            }
        """
        output_dict = {}

        pointer = 0
        segments_num = len(segments_input_dict['waveform'])

        while True:
            if pointer >= segments_num:
                break

            batch_input_dict = {}

            for key in segments_input_dict.keys():
                batch_input_dict[key] = torch.Tensor(
                    segments_input_dict[key][pointer : pointer + batch_size]
                ).to(self.device)

            pointer += batch_size

            with torch.no_grad():
                model.eval()
                batch_output_dict = model(batch_input_dict)

            for key in batch_output_dict.keys():
                self._append_to_dict(
                    output_dict, key, batch_output_dict[key].data.cpu().numpy()
                )

        for key in output_dict.keys():
            output_dict[key] = np.concatenate(output_dict[key], axis=0)

        return output_dict

    def _append_to_dict(self, dict, key, value):
        if key in dict.keys():
            dict[key].append(value)
        else:
            dict[key] = [value]


def inference(args):

    # Arguments & parameters
    audio_path = args.audio_path
    output_path = args.output_path
    select = args.select
    sample_rate = 44100
    segment_samples = int(30 * sample_rate)
    batch_size = 1
    device = "cuda"

    # Todo

    # checkpoint = torch.load(checkpoint_path, map_location='cpu')
    # model.load_state_dict(checkpoint["model"])

    # model.to(device)

    # separator = Separator(model, segment_samples, batch_size, device)

    # audio, _ = librosa.load(audio_path, sr=sample_rate, mono=False)

    # separate_time = time.time()
    # sep_wav = separator.separate(audio)
    # res_wav = audio - sep_wav
    # print('Separate time: {:.3f} s'.format(time.time() - separate_time))

    # # # Write out separated audio
    # soundfile.write(file=output_path, data=sep_wav.T, samplerate=sample_rate)
    # soundfile.write(file='_zz2.wav', data=res_wav.T, samplerate=sample_rate)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="")
    parser.add_argument("--audio_path", type=str, required=True)
    parser.add_argument("--output_path", type=str, required=True)
    parser.add_argument("--select", type=str, required=True)

    args = parser.parse_args()
    inference(args)
