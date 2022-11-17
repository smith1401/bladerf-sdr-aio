import asyncio
import concurrent.futures
import datetime as dt
import logging
import sys
from typing import Dict, AsyncGenerator, Generator
from typing import Optional, Union

import bladerf
import humanize
import numpy as np
import numpy.typing as npt
from bladerf._bladerf import ChannelLayout, Format

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def print_channel_info(ch: bladerf.BladeRF._Channel):
    """
    Print information about channel
    :param ch: Current channel (RX, TX)
    """
    print()
    print(ch)
    print('*' * 25)
    print(f'Frequency:\t\t{humanize.metric(ch.frequency, unit="Hz")}')
    print(f'Sample rate:\t{humanize.metric(ch.sample_rate, unit="S/s")}')
    print(f'Bandwidth:\t\t{humanize.metric(ch.bandwidth, unit="Hz")}')
    print('*' * 25)
    print()


class AioBladeRF(bladerf.BladeRF):
    """Asynchronous version of BladeRF object"""


    def __init__(
            self,
            device_identifier: str = None,
            devinfo: str = None,
            loop: Optional[asyncio.AbstractEventLoop] = None,
            cancel_receive_timeout: int = 1,
            cancel_send_timeout: int = 1):
        super().__init__(
            device_identifier=device_identifier,
            devinfo=devinfo)
        self._loop: Optional[asyncio.AbstractEventLoop] = loop

        self._cancel_receive_executor: concurrent.futures.ThreadPoolExecutor = \
            concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._cancel_receive_timeout: int = cancel_receive_timeout
        self._receive_executor: concurrent.futures.ThreadPoolExecutor = \
            concurrent.futures.ThreadPoolExecutor(max_workers=2)

        self._rx_locks: Dict[int, asyncio.Lock] = {
            bladerf.CHANNEL_RX(0): asyncio.Lock(),
            bladerf.CHANNEL_RX(1): asyncio.Lock(),
        }

        self._tx_locks: Dict[int, asyncio.Lock] = {
            bladerf.CHANNEL_TX(0): asyncio.Lock(),
            bladerf.CHANNEL_TX(1): asyncio.Lock(),
        }

        self._cancel_send_executor: concurrent.futures.ThreadPoolExecutor = \
            concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._cancel_send_timeout: int = cancel_send_timeout
        self._send_executor: concurrent.futures.ThreadPoolExecutor = \
            concurrent.futures.ThreadPoolExecutor(max_workers=2)

        self._bytes_per_sample = 4

        self._cancel_send_event: asyncio.Event = asyncio.Event()
        self._cancel_receive_event: asyncio.Event = asyncio.Event()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def cancel_receive(self):
        """Cancel receiving samples"""
        self._cancel_receive_event.set()

    def cancel_send(self):
        """Cancel sending samples"""
        self._cancel_send_event.set()

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Get current asyncio loop"""
        return self._loop if self._loop else asyncio.get_running_loop() \
            if sys.version_info >= (3, 7) else asyncio.get_event_loop()

    @loop.setter
    def loop(self, value: Optional[asyncio.AbstractEventLoop]):
        """Set current asyncio event loop"""
        self._loop = value

    async def receive_samples_async(self, rx_channel: bladerf.BladeRF._Channel, num_samples: int = 1024) -> npt.NDArray[
        np.complex64]:
        """
        Receive a certain amount of samples from the SDR asynchronously.
        :param rx_channel: Current RX channel
        :param num_samples: Number of samples to receive
        :return: IQ samples as numpy complex type
        """
        async with self._rx_locks[rx_channel.channel]:
            try:
                return await self.loop.run_in_executor(
                    self._receive_executor, self.receive_samples, rx_channel, num_samples)
            except asyncio.CancelledError:
                cancel_receive()
                raise

    async def receive_bytes_async(self, rx_channel: bladerf.BladeRF._Channel, num_bytes: int = 1024) -> bytes:
        """
        Receive a certain amount of bytes from the SDR asynchronously. Each sample consists of 4 bytes. Two for I and two
        for Q.
        :param rx_channel: Current RX channel
        :param num_bytes: Number of bytes to receive. Should be a multiple of four to receive the same amount of I and Q
        samples.
        :return: Array of bytes
        """
        async with self._rx_locks[rx_channel.channel]:
            try:
                return await self.loop.run_in_executor(
                    self._receive_executor, self.receive_bytes, rx_channel, num_bytes)
            except asyncio.CancelledError:
                cancel_receive()
                raise

    async def send_samples_async(self, tx_channel: bladerf.BladeRF._Channel,
                                 samples: npt.NDArray[np.complex64], repeat: int = 0):
        """
        Send samples to SDR asynchronously
        :param tx_channel: Current TX channel
        :param samples: Samples to be sent
        :param repeat: Number of times to repeat input data.
        repeat == 0   -> send once
        repeat > 0    -> send n times
        repeat == -1  -> repeat indefinitely until cancel_read has been executed
        """
        async with self._tx_locks[tx_channel.channel]:
            try:
                return await self.loop.run_in_executor(
                    self._send_executor, self.send_samples, tx_channel, samples, repeat)
            except asyncio.CancelledError:
                cancel_send()
                raise

    async def send_bytes_async(self, tx_channel: bladerf.BladeRF._Channel,
                               data: Union[bytearray, bytes, memoryview], repeat: int = 0):
        """
        Send bytes to SDR asynchronously
        :param tx_channel: Current TX channel
        :param data: Bytes to be sent
        :param repeat: Number of times to repeat input data.
        repeat == 0   -> send once
        repeat > 0    -> send n times
        repeat == -1  -> repeat indefinitely until cancel_read has been executed
        """
        async with self._tx_locks[tx_channel.channel]:
            try:
                return await self.loop.run_in_executor(
                    self._send_executor, self.send_bytes, tx_channel, data, repeat)
            except asyncio.CancelledError:
                cancel_send()
                raise

    async def stream_samples_async(self, rx_channel: bladerf.BladeRF._Channel, chunk_size: int = 8192) -> \
    AsyncGenerator[
        npt.NDArray[np.complex64], None]:
        """
        Stream samples asynchronously.
        :param rx_channel: Current RX channel
        :param chunk_size: Number of samples for each iteration
        :return: An asynchronous generator object
        """
        async with self._rx_locks[rx_channel.channel]:
            loop = asyncio.get_event_loop()
            try:
                self.sync_config(layout=ChannelLayout(rx_channel.channel),
                                 fmt=Format.SC16_Q11,
                                 num_buffers=16,
                                 buffer_size=8192,
                                 num_transfers=8,
                                 stream_timeout=3500)

                rx_channel.enable = True

                while True:
                    buf = bytearray(chunk_size * self._bytes_per_sample)
                    await loop.run_in_executor(self._receive_executor, self.sync_rx, buf,
                                               len(buf) // self._bytes_per_sample)
                    yield self._convert_bytes_to_samples(buf)

                    if self._cancel_receive_event.is_set():
                        break

                rx_channel.enable = False
            except asyncio.CancelledError:
                rx_channel.enable = False
                cancel_receive()
                raise

    try:
        import sigmf
        from sigmf import SigMFFile

        async def record_file_async(self, filename: str, rx_channel: bladerf.BladeRF._Channel, num_samples: int,
                                    info: str = ''):
            """
            Start the recording of an IQ sample file in the common .sigmf format. Two files will be generated. One file
            containing the data of the recording and the other file containing the metadata such as sampling rate.
            :param filename: Name of the file
            :param rx_channel: Current RX channel
            :param num_samples: Number of samples to record
            :param info: Optional info for metadata file
            """
            samples = await self.receive_samples_async(rx_channel, num_samples)

            # Save data file
            samples.tofile(f'{filename}.sigmf-data')

            # create the metadata
            meta = SigMFFile(
                data_file=f'{filename}.sigmf-data',  # extension is optional
                global_info={
                    SigMFFile.DATATYPE_KEY: 'cf32_le',  # get_data_type_str(samples),
                    SigMFFile.SAMPLE_RATE_KEY: self.get_sample_rate(rx_channel.channel),
                    SigMFFile.AUTHOR_KEY: 'IFG (navigation.ifg@gmail.com)',
                    SigMFFile.DESCRIPTION_KEY: info,
                    SigMFFile.VERSION_KEY: sigmf.__version__,
                }
            )

            # create a capture key at time index 0
            meta.add_capture(0, metadata={
                SigMFFile.FREQUENCY_KEY: self.get_frequency(rx_channel.channel),
                SigMFFile.DATETIME_KEY: dt.datetime.utcnow().isoformat() + 'Z',
            })

            # check for mistakes and write to disk
            assert meta.validate()
            meta.tofile(f'{filename}.sigmf-meta')  # extension is optional
    except ImportError:
        async def record_file_async(self, filename: str, rx_channel: bladerf.BladeRF._Channel, num_samples: int,
                                    info: str = ''):
            raise NotImplementedError

    def send_samples(self, tx_channel: bladerf.BladeRF._Channel,
                     samples: npt.NDArray[np.complex64], repeat: int = 0):
        """
        Send samples to SDR.
        :param tx_channel: Current TX channel
        :param samples: Samples to be sent
        :param repeat: Number of times to repeat input data.
        repeat == 0   -> send once
        repeat > 0    -> send n times
        repeat == -1  -> repeat indefinitely until cancel_read has been executed
        """
        data = (samples.view(np.float32).astype(np.float64) * 2048).astype(np.float32).astype(np.int16)
        self.send_bytes(tx_channel, data, repeat)

    def send_bytes(self, tx_channel: bladerf.BladeRF._Channel,
                   data: Union[bytearray, bytes, memoryview], repeat: int = 0):
        """
        Send bytes to SDR.
        :param tx_channel: Current TX channel
        :param data: Bytes to be sent
        :param repeat: Number of times to repeat input data.
        repeat == 0   -> send once
        repeat > 0    -> send n times
        repeat == -1  -> repeat indefinitely until cancel_read has been executed
        """
        self.sync_config(layout=ChannelLayout(tx_channel.channel),
                         fmt=Format.SC16_Q11,
                         num_buffers=16,
                         buffer_size=8192,
                         num_transfers=8,
                         stream_timeout=3500)

        tx_channel.enable = True
        log.info(f'Started writing samples at {dt.datetime.now()}')

        while True:
            self.sync_tx(data, len(data) // self._bytes_per_sample)

            # break immediately if cancel write event is set
            if self._cancel_send_event.is_set():
                break

            # repeat n times; if n == 0 execute just once; if n == -1 repeat indefinitely
            if repeat > 0:
                repeat -= 1
            elif repeat == 0:
                break

        tx_channel.enable = False
        log.info(f'Stopped writing samples at {dt.datetime.now()}')

    def receive_bytes(self, rx_channel: bladerf.BladeRF._Channel, num_bytes: int = 1024) -> bytes:
        """
        Receive a certain amount of bytes from the SDR. Each sample consists of 4 bytes. Two for I and two
        for Q.
        :param rx_channel: Current RX channel
        :param num_bytes: Number of bytes to receive. Should be a multiple of four to receive the same amount of I and Q
        samples.
        :return: Array of bytes
        """
        self.sync_config(layout=ChannelLayout(rx_channel.channel),
                         fmt=Format.SC16_Q11,
                         num_buffers=16,
                         buffer_size=8192,
                         num_transfers=8,
                         stream_timeout=3500)

        rx_channel.enable = True
        buf = bytearray(num_bytes)
        self.sync_rx(buf, num_bytes // self._bytes_per_sample)
        rx_channel.enable = False

        return buf

    def receive_samples(self, rx_channel: bladerf.BladeRF._Channel, num_samples: int = 1024) -> npt.NDArray[
        np.complex64]:
        """
        Receive a certain amount of samples from the SDR.
        :param rx_channel: Current RX channel
        :param num_samples: Number of samples to receive
        :return: IQ samples as numpy complex type
        """
        data = self.receive_bytes(rx_channel, num_samples * self._bytes_per_sample)
        samples = self._convert_bytes_to_samples(data)
        return samples

    def stream_samples(self, rx_channel: bladerf.BladeRF._Channel, chunk_size: int = 8192) -> Generator[npt.NDArray[
                                                                                                            np.complex64], None, None]:
        """
        Stream samples continuously.
        :param rx_channel: Current RX channel
        :param chunk_size: Number of samples for each iteration
        :return: A generator object
        """
        self.sync_config(layout=ChannelLayout(rx_channel.channel),
                         fmt=Format.SC16_Q11,
                         num_buffers=16,
                         buffer_size=8192,
                         num_transfers=8,
                         stream_timeout=3500)

        rx_channel.enable = True

        while True:
            buf = bytearray(chunk_size * self._bytes_per_sample)
            self.sync_rx(buf, len(buf))
            yield self._convert_bytes_to_samples(buf)

            if self._cancel_receive_event.is_set():
                break

        rx_channel.enable = False

    @staticmethod
    def _convert_bytes_to_samples(data: bytes) -> npt.NDArray[np.complex64]:
        """
        Convert bytes to samples in IQ complex format.
        :param data: Array of bytes
        :return: IQ samples as numpy complex type
        """
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        samples /= 2048
        samples = samples[::2] + 1j * samples[1::2]
        # samples = samples.view(np.complex64)
        return samples
