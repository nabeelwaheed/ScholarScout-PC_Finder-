import "../styles/globals.css";

export const metadata = {
  title: "ScholarScout",
  description: "Premium UI for PC recommendation API",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-black text-white">{children}</body>
    </html>
  );
}
