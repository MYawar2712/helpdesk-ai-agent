"use client";

import { useAuth } from "@/hooks/useAuth";

export function Header() {
  const { user } = useAuth();

  return (
    <header className="sticky top-0 z-40 bg-white border-b border-gray-200">
      <div className="flex items-center justify-between h-16 px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-900">Helpdesk Dashboard</h1>
        </div>

        <div className="flex items-center gap-4">
          <div className="hidden sm:block text-sm text-gray-500">
            Signed in as <span className="font-medium text-gray-900">{user?.email}</span>
          </div>
          <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center">
            <span className="text-blue-700 text-sm font-medium">
              {user?.email?.charAt(0)?.toUpperCase() || "U"}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
