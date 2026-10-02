import type {
  Conversation,
  ConversationDetail,
  CreateConversationResponse,
  LoginRequest,
  LoginResponse,
  SendMessageResponse,
  User,
} from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiClient {
  private token: string | null = null;

  setToken(token: string | null) {
    this.token = token;
    if (typeof window !== "undefined") {
      if (token) {
        localStorage.setItem("access_token", token);
      } else {
        localStorage.removeItem("access_token");
      }
    }
  }

  getToken(): string | null {
    if (this.token) return this.token;
    if (typeof window !== "undefined") {
      return localStorage.getItem("access_token");
    }
    return null;
  }

  async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = this.getToken();
    const headers: HeadersInit = {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    };

    let response: Response;
    try {
      response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers,
      });
    } catch {
      throw new Error(
        `Unable to reach the API at ${API_BASE}. Start the backend and verify NEXT_PUBLIC_API_URL.`
      );
    }

    if (response.status === 401) {
      this.setToken(null);
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
      throw new Error("Unauthorized");
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return response.json();
  }

  // Auth
  async login(credentials: LoginRequest): Promise<LoginResponse> {
    const response = await this.request<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    });
    this.setToken(response.access_token);
    // The API returns the token only. Resolve the profile separately so
    // role-based routing has the actual authenticated role available.
    const user = await this.getCurrentUser();
    return { ...response, user };
  }

  logout() {
    this.setToken(null);
  }

  async getCurrentUser(): Promise<User> {
    return this.request<User>("/auth/me");
  }

  // Conversations
  async listConversations(): Promise<Conversation[]> {
    return this.request<Conversation[]>("/chat/conversations");
  }

  async createConversation(): Promise<CreateConversationResponse> {
    return this.request<CreateConversationResponse>("/chat/conversations", {
      method: "POST",
      body: JSON.stringify({}),
    });
  }

  async getConversation(conversationId: string): Promise<ConversationDetail> {
    return this.request<ConversationDetail>(
      `/chat/conversations/${conversationId}`
    );
  }

  async sendMessage(
    conversationId: string,
    content: string
  ): Promise<SendMessageResponse> {
    return this.request<SendMessageResponse>(
      `/chat/conversations/${conversationId}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ content }),
      }
    );
  }

  async closeConversation(conversationId: string): Promise<void> {
    return this.request<void>(`/chat/conversations/${conversationId}`, {
      method: "DELETE",
    });
  }
}

export const api = new ApiClient();
