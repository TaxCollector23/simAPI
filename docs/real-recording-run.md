# Real recording validation run

## Source

The recording is `livingroom_T-shirt_folding_DualArxR5a_251110_173213_0.mcap` from IO Intelligence's public `FoldingTShirt_DualArxR5a_Samples` dataset. The dataset README describes Apache-2.0 licensed raw ROS 2 MCAP episodes recorded on a real DualArxR5a during teleoperation of the “Fold the T-shirt on the table” task. It documents `/io_teleop/joint_states` as a robot-state topic.

- [Dataset README and license](https://huggingface.co/datasets/io-intelligence/FoldingTShirt_DualArxR5a_Samples/blob/main/README.md)
- [Selected MCAP](https://huggingface.co/datasets/io-intelligence/FoldingTShirt_DualArxR5a_Samples/resolve/main/data/livingroom_T-shirt_folding_DualArxR5a_251110_173213_0.mcap)
- File size: 145,137,874 bytes (138.46 MiB)

The recording file was kept outside the repository.

## Run

Posted the file to the local `/v1/validate/recording` endpoint using `topic_hint=io_teleop/joint_states`. To exercise the parser and validator, the local process used `SIMAPI_MAX_UPLOAD_BYTES=200000000`; this was a test-only override and did not change the repository default.

The first run returned HTTP 400 because the MCAP connection used the legacy ROS message name `sensor_msgs/JointState`, while `rosbags` expects the canonical ROS 2 name `sensor_msgs/msg/JointState` for CDR deserialization. `integrations/ros2_loader.py` now normalizes that alias before deserializing, with regression coverage for both legacy and canonical names.

## Results and breakages

After the loader fix, the endpoint returned HTTP 200 and parsed 6,088 rows from one episode. The validation report returned `status=failed` and `training_ready=false`:

- `semantic_bounds:t` failed all 6,088 samples because the `t` column contains epoch-second timestamps around 1.762 billion, outside the semantic range applied to that column.
- `structural:exact_duplicate` reported 17 rows.
- `structural:near_duplicate` reported 1 row.
- `robotics_unprofiled_signal` warned that the joint signals had no robot-specific limits; this is the expected screening-only result when no profile or explicit limits are supplied.

The file is larger than the default upload limit of 104,857,600 bytes (100 MiB). With the default setting, the same upload returned HTTP 413 `payload_too_large` at 104,923,136 bytes. All 100 files in this dataset exceed the default cap, so the current public raw-capture examples cannot be uploaded without a larger configured limit or a smaller recording.

## Follow-up

The real-data run is now complete. Before treating this recording as training-ready, resolve the `t` semantic-bound conflict and provide robot-specific limits. Decide the next hard task with a named design partner, as required by the project spec.
