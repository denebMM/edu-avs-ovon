export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method Not Allowed' });
  }

  const { message, session_id } = req.body;

  if (!message || !session_id) {
    return res.status(400).json({ error: 'Message and session_id are required' });
  }

  try {
    const backendUrl = process.env.BACKEND_URL || 'http://localhost:8080';
    console.log('Attempting to fetch from:', `${backendUrl}/chat`);
    
    const response = await fetch(`${backendUrl}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': process.env.NEXT_PUBLIC_API_KEY,
      },
      body: JSON.stringify({ message, session_id }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('Backend API error:', response.status, errorText);
      throw new Error(`Backend API request failed: ${response.status} ${errorText}`);
    }

    const data = await response.json();
    res.status(200).json(data);
  } catch (error) {
    console.error('Error processing request:', error);
    res.status(500).json({ error: 'Error processing your request', details: error.message });
  }
}