import * as http from "http";

export interface Memory {
  slug: string;
  type: string;
  priority: number;
  rule: string;
  why?: string;
  when?: string;
  tags?: string[];
  score?: number;
}

export interface Checkpoint {
  sha: string;
  timestamp: string;
  message: string;
  added?: number;
  modified?: number;
  removed?: number;
}

export interface DaemonStatus {
  status: string;
  version: string;
  store: string;
  initialized: boolean;
  memory_count: number;
}

function request<T>(
  method: string,
  path: string,
  port: number,
  body?: unknown
): Promise<T> {
  return new Promise((resolve, reject) => {
    const payload = body ? JSON.stringify(body) : undefined;
    const options: http.RequestOptions = {
      hostname: "127.0.0.1",
      port,
      path,
      method,
      headers: {
        "Content-Type": "application/json",
        ...(payload ? { "Content-Length": Buffer.byteLength(payload) } : {}),
      },
    };

    const req = http.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        try {
          resolve(JSON.parse(data) as T);
        } catch {
          reject(new Error(`Invalid JSON: ${data}`));
        }
      });
    });

    req.on("error", reject);
    req.setTimeout(3000, () => {
      req.destroy();
      reject(new Error("Daemon request timed out"));
    });

    if (payload) req.write(payload);
    req.end();
  });
}

export class MemgitDaemonClient {
  constructor(private readonly port: number = 7474) {}

  async status(): Promise<DaemonStatus> {
    return request<DaemonStatus>("GET", "/status", this.port);
  }

  async listMemories(minPriority = 1): Promise<Memory[]> {
    return request<Memory[]>(
      "GET",
      `/memories?min_priority=${minPriority}`,
      this.port
    );
  }

  async getMemory(slug: string): Promise<Memory | null> {
    try {
      return await request<Memory>("GET", `/memories/${slug}`, this.port);
    } catch {
      return null;
    }
  }

  async searchMemories(query: string, topK = 8): Promise<Memory[]> {
    return request<Memory[]>("POST", "/memories/search", this.port, {
      query,
      top_k: topK,
    });
  }

  async saveMemory(
    slug: string,
    rule: string,
    priority = 2,
    tags: string[] = []
  ): Promise<{ status: string; action: string; slug: string }> {
    return request("PUT", `/memories/${slug}`, this.port, {
      rule,
      priority,
      tags,
    });
  }

  async getCheckpoints(limit = 10): Promise<Checkpoint[]> {
    return request<Checkpoint[]>(
      "GET",
      `/checkpoints?limit=${limit}`,
      this.port
    );
  }

  async isReachable(): Promise<boolean> {
    try {
      const s = await this.status();
      return s.status === "ok";
    } catch {
      return false;
    }
  }
}
