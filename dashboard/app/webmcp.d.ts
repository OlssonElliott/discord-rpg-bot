type WebMCPTool = {
  name: string;
  title?: string;
  description: string;
  inputSchema: object;
  annotations?: { readOnlyHint?: boolean; untrustedContentHint?: boolean };
  execute(input: unknown): unknown;
};

interface Document {
  readonly modelContext?: {
    registerTool(tool: WebMCPTool, options?: { signal?: AbortSignal }): void | Promise<void>;
  };
}
