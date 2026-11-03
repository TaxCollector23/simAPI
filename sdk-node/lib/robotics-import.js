import { XMLParser, XMLValidator } from "fast-xml-parser";
import {
  jointStem,
  normalize,
  numeric,
  validateProfile,
} from "./robotics-workflow.js";

export function profileFromUrdf(xml, name) {
  if (xml.length > 5_000_000 || /<!DOCTYPE|<!ENTITY|\$\{|xacro:/i.test(xml))
    throw new Error(
      "Use a resolved URDF under 5 MB. Xacro and entity declarations are not supported.",
    );
  const valid = XMLValidator.validate(xml);
  if (valid !== true) throw new Error(`Invalid URDF XML: ${valid.err.msg}`);
  const robot = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: "",
    parseAttributeValue: false,
  }).parse(xml).robot;
  if (!robot) throw new Error("URDF must have a robot root element.");
  const limits = {},
    units = {},
    joints = {},
    warnings = [],
    stems = new Set();
  for (const joint of [robot.joint ?? []].flat()) {
    if (!joint.name || !joint.type)
      throw new Error("Every URDF joint needs a name and type.");
    if (joint.type === "fixed") continue;
    if (!["revolute", "continuous", "prismatic"].includes(joint.type)) {
      warnings.push(`${joint.name}: ${joint.type} joints need manual limits.`);
      continue;
    }
    const stem = jointStem(joint.name);
    if (stems.has(stem))
      throw new Error(`Joint names collide after normalization: ${joint.name}`);
    stems.add(stem);
    joints[joint.name] = { stem, type: joint.type };
    const range = joint.limit ?? {},
      linear = joint.type === "prismatic";
    if (joint.type !== "continuous") {
      const low = numeric(range.lower),
        high = numeric(range.upper);
      if (low !== null && high !== null && low < high) {
        limits[`${stem}_position`] = [low, high];
        units[`${stem}_position`] = linear ? "m" : "rad";
      } else
        warnings.push(`${joint.name}: no usable position range was declared.`);
    } else
      warnings.push(
        `${joint.name}: continuous joint has no position bound; provide unwrapped positions.`,
      );
    for (const [attr, quantity, unit] of [
      ["velocity", "velocity", linear ? "m/s" : "rad/s"],
      ["effort", linear ? "force" : "torque", linear ? "N" : "Nm"],
    ]) {
      const v = numeric(range[attr]);
      if (v !== null && v > 0) {
        limits[`${stem}_${quantity}`] = [-v, v];
        units[`${stem}_${quantity}`] = unit;
      } else
        warnings.push(`${joint.name}: no positive ${attr} limit was declared.`);
    }
  }
  if (!Object.keys(limits).length)
    throw new Error("URDF contains no usable arm joint limits.");
  warnings.push(
    "URDF does not define acceleration limits; configure them explicitly when available.",
  );
  return validateProfile({
    schema_version: 1,
    name: name || robot.name || "Arm profile",
    robotics_limits: limits,
    conditions: {},
    joints,
    units,
    warnings,
    source: "urdf",
  });
}

function stampSeconds(stamp) {
  if (!stamp || typeof stamp !== "object") return null;
  const sec = numeric(stamp.sec ?? stamp.secs),
    ns = numeric(stamp.nanosec ?? stamp.nsec ?? stamp.nsecs ?? 0);
  return sec !== null && ns !== null ? sec + ns / 1e9 : null;
}
export function jointStateRow(
  message,
  logTime,
  episode = "recording",
  profile,
) {
  const names = message.name;
  if (!Array.isArray(names) || !names.length) {
    if (
      message &&
      Object.keys(message).some((k) => normalize(k).startsWith("joint"))
    )
      return {
        ...message,
        episode_id: message.episode_id ?? episode,
        time: numeric(message.time) ?? logTime,
      };
    throw new Error(
      "Expected sensor_msgs/JointState with a non-empty name array, or JSON joint signals.",
    );
  }
  const row = {
      episode_id: episode,
      time: stampSeconds(message.header?.stamp) ?? logTime,
    },
    stems = new Set();
  for (let i = 0; i < names.length; i++) {
    const stem = jointStem(names[i]);
    if (stems.has(stem))
      throw new Error(
        `Duplicate joint signal after normalization: ${names[i]}`,
      );
    stems.add(stem);
    for (const [field, quantity] of [
      ["position", "position"],
      ["velocity", "velocity"],
      [
        "effort",
        profile?.joints?.[names[i]]?.type === "prismatic" ? "force" : "torque",
      ],
    ]) {
      const values = message[field];
      if (!values || values.length === 0) continue;
      if (values.length !== names.length)
        throw new Error(
          `JointState ${field} length does not match name length.`,
        );
      row[`${stem}_${quantity}`] = numeric(values[i]);
    }
  }
  return row;
}

export async function readRecording(bytes, filename, options = {}) {
  if (!(bytes instanceof Uint8Array) || !bytes.length)
    throw new Error("Choose a non-empty recording.");
  if (bytes.length > 100 * 1024 * 1024)
    throw new Error(
      "Recordings are limited to 100 MB. Export a smaller capture.",
    );
  const { loadDecompressHandlers } = await import("@mcap/support");
  const handlers = await loadDecompressHandlers(),
    messages = [],
    topics = new Map();
  const maxSamples = 10000;
  if (/\.mcap$/i.test(filename)) {
    const { McapStreamReader } = await import("@mcap/core");
    const { parse } = await import("@foxglove/rosmsg");
    const { MessageReader: Ros1 } =
      await import("@foxglove/rosmsg-serialization");
    const { MessageReader: Ros2 } =
      await import("@foxglove/rosmsg2-serialization");
    const reader = new McapStreamReader({ decompressHandlers: handlers }),
      schemas = new Map(),
      channels = new Map(),
      decoders = new Map();
    reader.append(bytes);
    for (let rec; (rec = reader.nextRecord());) {
      if (rec.type === "Schema") schemas.set(rec.id, rec);
      if (rec.type === "Channel") {
        channels.set(rec.id, rec);
        const schema = schemas.get(rec.schemaId);
        if (
          !topics.has(rec.topic) &&
          (/JointState$/.test(schema?.name ?? "") ||
            rec.messageEncoding === "json")
        )
          topics.set(rec.topic, {
            topic: rec.topic,
            schema: schema?.name ?? "JSON",
            encoding: rec.messageEncoding,
            samples: 0,
          });
      }
      if (rec.type !== "Message") continue;
      const channel = channels.get(rec.channelId);
      if (!channel || !topics.has(channel.topic)) continue;
      topics.get(channel.topic).samples++;
      if (options.topic && channel.topic !== options.topic) continue;
      // A selection is required for multi-topic recordings. Retain at most the service limit per topic.
      if (topics.get(channel.topic).samples > maxSamples) continue;
      const schema = schemas.get(channel.schemaId);
      let message;
      if (channel.messageEncoding === "json")
        message = JSON.parse(new TextDecoder().decode(rec.data));
      else {
        if (!schema || !["ros1msg", "ros2msg"].includes(schema.encoding))
          throw new Error(
            `Unsupported schema on ${channel.topic}. Use ros1msg, ros2msg, or JSON MCAP.`,
          );
        if (!decoders.has(channel.id)) {
          const definition = parse(new TextDecoder().decode(schema.data), {
            ros2: schema.encoding === "ros2msg",
          });
          decoders.set(
            channel.id,
            channel.messageEncoding === "cdr"
              ? new Ros2(definition)
              : channel.messageEncoding === "ros1"
                ? new Ros1(definition)
                : null,
          );
        }
        const decoder = decoders.get(channel.id);
        if (!decoder)
          throw new Error(
            `Unsupported message encoding: ${channel.messageEncoding}`,
          );
        message = decoder.readMessage(rec.data);
      }
      messages.push({
        topic: channel.topic,
        time:
          Number(rec.logTime / 1_000_000_000n) +
          Number(rec.logTime % 1_000_000_000n) / 1e9,
        message,
      });
    }
    if (!reader.done()) throw new Error("MCAP is truncated or incomplete.");
  } else if (/\.bag$/i.test(filename)) {
    const { Bag } = await import("@foxglove/rosbag");
    const bag = new Bag(
      {
        size: () => bytes.length,
        read: async (offset, length) => bytes.subarray(offset, offset + length),
      },
      {
        decompress: {
          bz2: (b, size) => handlers.bz2(b, BigInt(size)),
          lz4: (b, size) => handlers.lz4(b, BigInt(size)),
        },
      },
    );
    await bag.open();
    for (const connection of bag.connections.values())
      if (/JointState$/.test(connection.type))
        topics.set(connection.topic, {
          topic: connection.topic,
          schema: connection.type,
          encoding: "ros1",
          samples: 0,
        });
    const selected = options.topic ? [options.topic] : [...topics.keys()];
    for await (const event of bag.messageIterator({ topics: selected })) {
      if (!topics.has(event.topic)) continue;
      topics.get(event.topic).samples++;
      if (topics.get(event.topic).samples > maxSamples) continue;
      messages.push({
        topic: event.topic,
        time: stampSeconds(event.timestamp),
        message: event.message,
      });
    }
  } else
    throw new Error(
      "Use a ROS 1 .bag or ROS 1/2 .mcap file. ROS 2 SQLite .db3 bags must be exported to MCAP first.",
    );
  if (!topics.size)
    throw new Error("No JointState or JSON channels found in this recording.");
  if (options.topic && !topics.has(options.topic))
    throw new Error(
      `Topic not found. Choose: ${[...topics.keys()].join(", ")}`,
    );
  if (!options.topic && topics.size > 1)
    return {
      topics: [...topics.values()],
      requires_topic: true,
      rows: [],
      source: filename,
    };
  const topic = options.topic ?? [...topics.keys()][0];
  if (topics.get(topic).samples > maxSamples)
    throw new Error(
      `Topic ${topic} exceeds 10,000 samples. Export a shorter capture; data was not truncated.`,
    );
  const rows = messages
    .filter((m) => m.topic === topic)
    .map((m) =>
      jointStateRow(
        m.message,
        m.time,
        options.episode || "recording",
        options.profile,
      ),
    );
  if (!rows.length) throw new Error("Selected topic contains no samples.");
  return {
    topics: [...topics.values()],
    requires_topic: false,
    rows,
    source: filename,
    topic,
  };
}
