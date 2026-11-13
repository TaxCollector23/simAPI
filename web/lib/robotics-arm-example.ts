/** Built-in arm sample used by the robotics playground. */
export const roboticsArmExample = ["reach", "place"].flatMap((episode_id, episode) =>
  Array.from({ length: 6 }, (_, sample) => ({
    episode_id,
    time: Number((sample * 0.1).toFixed(2)),
    joint_1_position: Number((episode * 0.4 + sample * 0.05).toFixed(3)),
    joint_1_velocity: 0.5,
    joint_1_acceleration: 0,
    joint_1_torque: 12 + sample * 0.3,
    joint_2_position: Number((0.4 - sample * 0.025).toFixed(3)),
    joint_2_velocity: -0.25,
    joint_2_acceleration: 0,
    joint_2_torque: 8 + sample * 0.2,
    end_effector_force: 15 + sample * 0.5,
  })),
);

/** Example per-signal position range shown in README.md. */
export const roboticsPositionExampleRange = [-1.57, 1.57] as const;
