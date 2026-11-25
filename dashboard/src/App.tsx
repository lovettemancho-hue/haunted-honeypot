import { AuthProvider, useAuth } from "./auth/AuthContext";
import { AuthedApp } from "./AuthedApp";
import { LoginScreen } from "./pages/LoginScreen";

function AuthGate() {
  const { token } = useAuth();
  return token ? <AuthedApp /> : <LoginScreen />;
}

export default function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  );
}
