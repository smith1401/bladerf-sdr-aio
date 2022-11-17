# BladeRF SDR asynchronous wrapper

A python wrapper for the bladerf python bindings from Nuand. It provides synchronous as well as asynchronous functionality to send and receive data to and from the BladeRF SDR.

## Installation
- To install the requirements for this package: `python3 -m pip install -r requirements.txt
`
- To install system-wide: `sudo python3 setup.py install`
- To install for your user: `python3 setup.py install`

## Usage

Below is an example of how to use the asynchronous wrapper with a python context manager and an asynchronous generator
to continuously receive samples from the SDR for 5 seconds.

```python
import asyncio
import bladerf
from bladerfsdraio import AioBladeRF


async def main():
    with AioBladeRF() as sdr:
        ch_rx = sdr.Channel(bladerf.CHANNEL_RX(0))
        ch_rx.sample_rate = 1e6
        ch_rx.frequency = 1e9

        async def stream_samples(sdr: AioBladeRF):
            async for samples in sdr.stream_samples_async(ch_rx, chunk_size=1024):
                # .. handle samples
                print(samples.max())

        async def cancel_after(secs: float, sdr: AioBladeRF):
            await asyncio.sleep(secs)
            sdr.cancel_receive()

        await asyncio.gather(
            stream_samples(sdr),
            cancel_after(5, sdr)
        )


if __name__ == '__main__':
    asyncio.run(main())
```