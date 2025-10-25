## Extracting samples
To extract audio samples from the rom:
```
./extract-samples.py [ROM]
```
For example for `ddpdojblk`:
```
./extract-samples.py cave_m04401b032.u17 32
```
The samples will be written to the `samples/` directory. The audio format according to mame
is `8 bit mono 11025Hz`, but I was only able to get correct sounding samples when playing at
8000Hz sample rate. You can use `mpv` to play the samples back:
```
mpv --demuxer=rawaudio --demuxer-rawaudio-rate=8000 --demuxer-rawaudio-format=s8 --audio-channels=mono sample_*
```
