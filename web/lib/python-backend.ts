/** Python is the primary hosted engine. Override only for another deployment. */
export const PYTHON_API = (process.env.PYTHON_API_URL || "https://simapi-engine.onrender.com").replace(/\/$/, "");
