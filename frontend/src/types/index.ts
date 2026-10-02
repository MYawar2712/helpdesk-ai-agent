export interface User {
  id: string;
  email: string;
  role: string;
  tenant_id: string;
  customer_id?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  conversation_id: string;
  tenant_id: string;
  customer_id: string;
  ticket_id?: string;
  subject: string;
  status: "open" | "closed";
  created_at: string;
  updated_at: string;
}

export interface Message {
  message_id: string;
  conversation_id: string;
  sender_type: "CUSTOMER" | "AI";
  content: string;
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface SendMessageRequest {
  content: string;
}

export interface SendMessageResponse {
  conversation_id: string;
  message_id: string;
  sender: "AI";
  content: string;
  created_at: string;
}

// CreateConversationResponse is compatible with Conversation - the API returns the created conversation
export type CreateConversationResponse = Conversation;

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface ApiError {
  detail: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
