"""
Bonito POD5 Utils
"""

from glob import glob
from uuid import UUID
from pathlib import Path
from datetime import timedelta

import numpy as np
import bonito.reader
from tqdm import tqdm
from pod5_format import CombinedReader


class Read(bonito.reader.Read):

    def __init__(self, read, filename, meta=False):

        self.meta = meta

        self.read_id = read.read_id
        self.run_info = read.run_info
        self.filename = filename.name

        self.sample_id = self.run_info.sample_id
        self.run_id = self.run_info.acquisition_id
        self.acquisition_start_time = self.run_info.acquisition_start_time
        self.exp_start_time = self.acquisition_start_time.isoformat().replace('Z', '')

        self.flow_cell_id = self.run_info.flow_cell_id
        self.device_id = self.run_info.sequencer_position

        if self.meta:
            return

        self.pore = read.pore
        self.mux = self.pore.well
        self.channel = self.pore.channel
        self.read_number = read.read_number
        self.num_samples = read.sample_count

        self.context_tags = dict(self.run_info.context_tags)
        self.sample_rate = int(self.context_tags['sample_frequency'])

        self.start = read.start_sample / self.sample_rate
        self.duration = self.num_samples / self.sample_rate

        start_time = self.acquisition_start_time + timedelta(seconds=self.start)
        self.start_time = start_time.replace(microsecond=0).isoformat()

        self.raw = read.signal

        self.calibration = read.calibration
        self.scaling = self.calibration.scale
        self.offset = self.calibration.offset

        scaled = self.scaling * (self.raw.astype(np.float32) + self.offset)
        trim_start, _ = bonito.reader.trim(scaled[:8000])
        scaled = scaled[trim_start:]
        self.trimmed_samples = trim_start

        self.template_start = self.start + (trim_start / self.sample_rate)
        self.template_duration = self.duration - (trim_start / self.sample_rate)

        self.signal = scaled

        if len(scaled) > 8000:
            self.med, self.mad = bonito.reader.med_mad(scaled)
            self.mad = max(1.0, self.mad)
            self.signal = (scaled - self.med) / self.mad
        else:
            self.signal, (self.med, self.mad) = bonito.reader.norm_by_noisiest_section(scaled, return_medmad=True)


def pod5_reads(pod5_file, read_ids, skip=False):
    """
    Get all the reads from the `pod5_file`.
    """
    if read_ids is not None:
        yield from CombinedReader(pod5_file).reads(selection=[UUID(rid) for rid in read_ids], missing_ok=True, preload=["samples"])
    elif skip:
        for read in CombinedReader(pod5_file).reads(preload=["samples"]):
            if str(read.read_id) not in read_ids:
                yield read
    else:
        yield from CombinedReader(pod5_file).reads(preload=["samples"])


def get_read_groups(pod5_files, model, read_ids=None, skip=False, n_proc=1, cancel=None):
    """
    Get all the read meta data from pod5 files.
    """
    groups = set()
    num_reads = 0

    for pod5_file in pod5_files:
        for read in tqdm(
            pod5_reads(pod5_file, read_ids, skip),
            leave=False, desc="> preprocessing reads", unit=" reads/s", ascii=True, ncols=100
        ):
            read = Read(read, pod5_file, meta=True)
            groups.add(read.readgroup(model))
            num_reads += 1
    return groups, num_reads


def get_reads(pod5_files, read_ids=None, skip=False, n_proc=1, cancel=None):
    """
    Get all reads from pod5 files.
    """
    for pod5_file in pod5_files:
        for read in pod5_reads(pod5_file, read_ids, skip):
            yield Read(read, pod5_file)
            if cancel is not None and cancel.is_set():
                return
