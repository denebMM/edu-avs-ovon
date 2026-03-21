// pages/api/solve.js

export default async function handler(req, res) {
  // Only allow POST requests
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method Not Allowed' });
  }

  const { question } = req.body;

  if (!question) {
    return res.status(400).json({ error: 'Question is required' });
  }

  try {
    // Here you would make a call to your backend API
    // For now, we'll use a placeholder response
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    
    const response = await fetch(`${backendUrl}/solve`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ question }),
    });

    if (!response.ok) {
      throw new Error('Backend API request failed');
    }

    const data = await response.json();

    res.status(200).json({ solution: data.solution });
  } catch (error) {
    console.error('Error processing request:', error);
    res.status(500).json({ error: 'Error processing your request' });
  }
}