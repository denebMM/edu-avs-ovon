export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method Not Allowed' });
  }

  try {
    const backendUrl = process.env.BACKEND_URL || 'http://localhost:8080';
    
    const response = await fetch(`${backendUrl}/start_session`, {
      method: 'POST',
      headers: {
        'X-API-Key': process.env.NEXT_PUBLIC_API_KEY,
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('Backend API error:', response.status, errorText);
      throw new Error(`Backend API request failed: ${response.status} ${errorText}`);
    }

    const data = await response.json();
    res.status(200).json(data);
  } catch (error) {
    console.error('Error starting new session:', error);
    res.status(500).json({ error: 'Error starting new session' });
  }
}