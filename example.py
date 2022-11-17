import asyncio
import bladerf
from bladerfsdraio import AioBladeRF


async def main():
    with AioBladeRF() as sdr:
        ch_rx = sdr.Channel(bladerf.CHANNEL_RX(0))
        ch_rx.sample_rate = 1e6
        ch_rx.frequency = 1e9

        async def stream_samples(sdr: AioBladeRF):
            async for samples in sdr.stream_samples_async(ch_rx, chunk_size=int(1e6)):
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