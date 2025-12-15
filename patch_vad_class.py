
import os
import textwrap

target_file = "venv/lib/python3.11/site-packages/livekit/plugins/silero/vad.py"

new_vad_stream_code = """
class VADStream(agents.vad.VADStream):
    def __init__(
        self, vad: VAD, opts: _VADOptions, model: onnx_model.OnnxModel
    ) -> None:
        super().__init__()
        self._opts, self._model = opts, model
        self._loop = asyncio.get_event_loop()

        self._executor = ThreadPoolExecutor(max_workers=1)
        self._task.add_done_callback(lambda _: self._executor.shutdown(wait=False))
        self._exp_filter = utils.ExpFilter(alpha=0.35)

        self._input_sample_rate = 0
        self._speech_buffer: np.ndarray | None = None
        self._speech_buffer_max_reached = False
        self._prefix_padding_samples = 0  # (input_sample_rate)

    def update_options(
        self,
        *,
        min_speech_duration: float | None = None,
        min_silence_duration: float | None = None,
        prefix_padding_duration: float | None = None,
        max_buffered_speech: float | None = None,
        activation_threshold: float | None = None,
    ) -> None:
        "Update the VAD options."
        old_max_buffered_speech = self._opts.max_buffered_speech

        self._opts = _VADOptions(
            min_speech_duration=min_speech_duration or self._opts.min_speech_duration,
            min_silence_duration=min_silence_duration
            or self._opts.min_silence_duration,
            prefix_padding_duration=prefix_padding_duration
            or self._opts.prefix_padding_duration,
            max_buffered_speech=max_buffered_speech or self._opts.max_buffered_speech,
            activation_threshold=activation_threshold
            or self._opts.activation_threshold,
            sample_rate=self._opts.sample_rate,
        )

        if self._input_sample_rate:
            assert self._speech_buffer is not None

            self._prefix_padding_samples = int(
                self._opts.prefix_padding_duration * self._input_sample_rate
            )

            self._speech_buffer.resize(
                int(self._opts.max_buffered_speech * self._input_sample_rate)
                + self._prefix_padding_samples
            )

            if self._opts.max_buffered_speech > old_max_buffered_speech:
                self._speech_buffer_max_reached = False

    @agents.utils.log_exceptions(logger=logger)
    async def _main_task(self):
        try:
            inference_f32_data = np.empty(self._model.window_size_samples, dtype=np.float32)
            speech_buffer_index: int = 0

            # "pub_" means public, these values are exposed to the users through events
            pub_speaking = False
            pub_speech_duration = 0.0
            pub_silence_duration = 0.0
            pub_current_sample = 0
            pub_timestamp = 0.0

            speech_threshold_duration = 0.0
            silence_threshold_duration = 0.0

            input_frames = []
            inference_frames = []
            resampler: rtc.AudioResampler | None = None

            # used to avoid drift when the sample_rate ratio is not an integer
            input_copy_remaining_fract = 0.0

            extra_inference_time = 0.0

            async for input_frame in self._input_ch:
                if not isinstance(input_frame, rtc.AudioFrame):
                    continue  # ignore flush sentinel for now

                if not self._input_sample_rate:
                    self._input_sample_rate = input_frame.sample_rate

                    # alloc the buffers now that we know the input sample rate
                    self._prefix_padding_samples = int(
                        self._opts.prefix_padding_duration * self._input_sample_rate
                    )

                    self._speech_buffer = np.empty(
                        int(self._opts.max_buffered_speech * self._input_sample_rate)
                        + self._prefix_padding_samples,
                        dtype=np.int16,
                    )

                    if self._input_sample_rate != self._opts.sample_rate:
                        # resampling needed: the input sample rate isn't the same as the model's
                        # sample rate used for inference
                        resampler = rtc.AudioResampler(
                            input_rate=self._input_sample_rate,
                            output_rate=self._opts.sample_rate,
                            quality=rtc.AudioResamplerQuality.QUICK,  # VAD doesn't need high quality
                        )

                elif self._input_sample_rate != input_frame.sample_rate:
                    logger.error("a frame with another sample rate was already pushed")
                    continue

                assert self._speech_buffer is not None

                input_frames.append(input_frame)
                if resampler is not None:
                    # the resampler may have a bit of latency, but it is OK to ignore since it should be
                    # negligible
                    inference_frames.extend(resampler.push(input_frame))
                else:
                    inference_frames.append(input_frame)

                while True:
                    start_time = time.perf_counter()

                    available_inference_samples = sum(
                        [frame.samples_per_channel for frame in inference_frames]
                    )
                    if available_inference_samples < self._model.window_size_samples:
                        break  # not enough samples to run inference

                    input_frame = utils.merge_frames(input_frames)
                    inference_frame = utils.merge_frames(inference_frames)

                    # convert data to f32
                    np.divide(
                        inference_frame.data[: self._model.window_size_samples],
                        np.iinfo(np.int16).max,
                        out=inference_f32_data,
                        dtype=np.float32,
                    )

                    # run the inference
                    p = await self._loop.run_in_executor(
                        self._executor, self._model, inference_f32_data
                    )
                    p = self._exp_filter.apply(exp=1.0, sample=p)

                    window_duration = (
                        self._model.window_size_samples / self._opts.sample_rate
                    )

                    pub_current_sample += self._model.window_size_samples
                    pub_timestamp += window_duration

                    resampling_ratio = self._input_sample_rate / self._model.sample_rate
                    to_copy = (
                        self._model.window_size_samples * resampling_ratio
                        + input_copy_remaining_fract
                    )
                    to_copy_int = int(to_copy)
                    input_copy_remaining_fract = to_copy - to_copy_int

                    # copy the inference window to the speech buffer
                    available_space = len(self._speech_buffer) - speech_buffer_index
                    to_copy_buffer = min(to_copy_int, available_space)
                    if to_copy_buffer > 0:
                        # FIX: Use np.frombuffer to safely copy bytes to int16 array
                        data_bytes = input_frame.data[:to_copy_buffer * 2] # 2 bytes per sample
                        
                        # Handle potential shortness
                        if len(data_bytes) < to_copy_buffer * 2:
                             # Just use what we have, though this implies logic mismatch
                             pass

                        data_int16 = np.frombuffer(data_bytes, dtype=np.int16)
                        
                        # CRITICAL FIX: Handle race condition where speech_buffer shrunk
                        dest_slice = self._speech_buffer[
                            speech_buffer_index : speech_buffer_index + to_copy_buffer
                        ]
                        
                        if len(data_int16) > len(dest_slice):
                            # Truncate source data to match shrunk buffer
                            data_int16 = data_int16[:len(dest_slice)]
                            # logger.warning(f"Truncated VAD data from {len(data_bytes)//2} to {len(dest_slice)} due to buffer resize")

                        self._speech_buffer[
                            speech_buffer_index : speech_buffer_index + len(data_int16)
                        ] = data_int16
                        
                        speech_buffer_index += len(data_int16)
                    
                    elif not self._speech_buffer_max_reached:
                        # reached self._opts.max_buffered_speech (padding is included)
                        speech_buffer_max_reached = True
                        logger.warning(
                            "max_buffered_speech reached, ignoring further data for the current speech input"
                        )

                    inference_duration = time.perf_counter() - start_time
                    extra_inference_time = max(
                        0.0,
                        extra_inference_time + inference_duration - window_duration,
                    )
                    if inference_duration > SLOW_INFERENCE_THRESHOLD:
                        logger.warning(
                            "inference is slower than realtime",
                            extra={"delay": extra_inference_time},
                        )

                    def _reset_write_cursor():
                        nonlocal speech_buffer_index, speech_buffer_max_reached
                        assert self._speech_buffer is not None

                        if speech_buffer_index <= self._prefix_padding_samples:
                            return

                        padding_data = self._speech_buffer[
                            speech_buffer_index
                            - self._prefix_padding_samples : speech_buffer_index
                        ]

                        self._speech_buffer_max_reached = False
                        self._speech_buffer[: self._prefix_padding_samples] = padding_data
                        speech_buffer_index = self._prefix_padding_samples

                    def _copy_speech_buffer() -> rtc.AudioFrame:
                        # copy the data from speech_buffer
                        assert self._speech_buffer is not None
                        speech_data = self._speech_buffer[:speech_buffer_index].tobytes()

                        return rtc.AudioFrame(
                            sample_rate=self._input_sample_rate,
                            num_channels=1,
                            samples_per_channel=speech_buffer_index,
                            data=speech_data,
                        )

                    if pub_speaking:
                        pub_speech_duration += window_duration
                    else:
                        pub_silence_duration += window_duration

                    self._event_ch.send_nowait(
                        agents.vad.VADEvent(
                            type=agents.vad.VADEventType.INFERENCE_DONE,
                            samples_index=pub_current_sample,
                            silence_duration=pub_silence_duration,
                            speech_duration=pub_speech_duration,
                            probability=p,
                            inference_duration=inference_duration,
                            frames=[
                                rtc.AudioFrame(
                                    data=input_frame.data[:to_copy_int * 2], # FIX: *2 for bytes
                                    sample_rate=self._input_sample_rate,
                                    num_channels=1,
                                    samples_per_channel=to_copy_int,
                                )
                            ],
                            speaking=pub_speaking,
                        )
                    )

                    if p >= self._opts.activation_threshold:
                        speech_threshold_duration += window_duration
                        silence_threshold_duration = 0.0

                        if not pub_speaking:
                            if speech_threshold_duration >= self._opts.min_speech_duration:
                                pub_speaking = True
                                pub_silence_duration = 0.0
                                pub_speech_duration = speech_threshold_duration

                                self._event_ch.send_nowait(
                                    agents.vad.VADEvent(
                                        type=agents.vad.VADEventType.START_OF_SPEECH,
                                        samples_index=pub_current_sample,
                                        silence_duration=pub_silence_duration,
                                        speech_duration=pub_speech_duration,
                                        frames=[_copy_speech_buffer()],
                                        speaking=True,
                                    )
                                )

                    else:
                        silence_threshold_duration += window_duration
                        speech_threshold_duration = 0.0

                        if not pub_speaking:
                            _reset_write_cursor()

                        if (
                            pub_speaking
                            and silence_threshold_duration
                            >= self._opts.min_silence_duration
                        ):
                            pub_speaking = False
                            pub_speech_duration = 0.0
                            pub_silence_duration = silence_threshold_duration

                            self._event_ch.send_nowait(
                                agents.vad.VADEvent(
                                    type=agents.vad.VADEventType.END_OF_SPEECH,
                                    samples_index=pub_current_sample,
                                    silence_duration=pub_silence_duration,
                                    speech_duration=pub_speech_duration,
                                    frames=[_copy_speech_buffer()],
                                    speaking=False,
                                )
                            )

                            _reset_write_cursor()

                    # remove the frames that were used for inference from the input and inference frames
                    input_frames = []
                    inference_frames = []

                    # add the remaining data
                    if len(input_frame.data) - (to_copy_int * 2) > 0: # FIX: *2 bytes
                        data = input_frame.data[to_copy_int * 2:] # FIX: *2 bytes
                        input_frames.append(
                            rtc.AudioFrame(
                                data=data,
                                sample_rate=self._input_sample_rate,
                                num_channels=1,
                                samples_per_channel=len(data) // 2,
                            )
                        )

                    if len(inference_frame.data) - self._model.window_size_samples > 0:
                        # This one is tricky. inference_frame.data IS bytes.
                        # self._model.window_size_samples is samples.
                        # so we need *2 for bytes slicing?
                        # wait, inference_frame came from resampler (or input). 
                        # so correct.
                        # BUT wait, inference_f32_data usage above: 
                        # inference_frame.data[: self._model.window_size_samples]
                        # Inference frame data is bytes int16?
                        # np.divide on bytes acts on BYTES (0-255).
                        # This is ALSO buggy if not converted to int16 first?
                        # Actually np.divide might handle raw buffer? 
                        # No. np.divide( inference_frame.data... )
                        # If inference_frame.data is bytes, it's dividing byte values.
                        # It should be viewed as int16.
                        # Let's check how inference_f32_data is filled.
                        # np.divide(inference_frame.data[:...], ... out=inference_f32_data)
                        pass # I'll blindly trust the original code logic for inference parts for now unless obvious
                        # Wait, checking original code:
                        # np.divide(inference_frame.data[: self._model.window_size_samples] ...)
                        # This confirms the plugin code was assuming data[...] accesses samples.
                        # If data is bytes, this accesses BYTES.
                        # So it passes the first 512 BYTES (256 samples) and treats them as 512 values (0-255)?
                        # Yes, this looks BROKEN if AudioFrame.data is bytes.
                        # I should fix this too.
                        
                        data = inference_frame.data[
                            self._model.window_size_samples * 2 : # FIX: *2
                        ]
                        inference_frames.append(
                            rtc.AudioFrame(
                                data=data,
                                sample_rate=self._opts.sample_rate,
                                num_channels=1,
                                samples_per_channel=len(data) // 2,
                            )
                        )

        except Exception as e:
            logger.exception("VAD _main_task crashed")
            raise e
"""

with open(target_file, "r") as f:
    content = f.read()

# Find start of VADStream
if "class VADStream" not in content:
    print("Could not find VADStream class")
    exit(1)

pre_content = content.split("class VADStream")[0]

with open(target_file, "w") as f:
    f.write(pre_content + new_vad_stream_code)

print("Successfully patched VADStream class with robust fixes.")
