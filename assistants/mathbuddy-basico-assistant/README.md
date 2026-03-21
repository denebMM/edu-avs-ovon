# MathBuddy: AI-Powered Math Tutoring

MathBuddy is an AI-powered math tutoring application designed to assist students from basic arithmetic to Calculus 1. It combines advanced language models with mathematical computation engines to provide personalized, interactive math assistance.

## Key Features

- AI-Driven Tutoring: Uses GPT-4o for main interactions
- Precision Calculations: Integrates Wolfram Alpha, parsed by GPT-3.5-Turbo
- Dynamic Difficulty Adjustment: Employs GPT-3.5-Turbo for adaptive learning
- LaTeX Support: Renders mathematical expressions clearly
- Session-Based Learning: Maintains context for cohesive tutoring

## Architecture

```mermaid
graph TD
    subgraph Frontend
    A[Next.js App]
    end
    subgraph "API Layer"
    B[API Routes]
    end
    subgraph "Backend Server"
    C[FastAPI]
    D[Session Management]
    E[Rate Limiting]
    end
    subgraph "AI Processing"
    F[OpenAI GPT-4o]
    G[GPT-3.5-Turbo<br>Result Extractor]
    H[GPT-3.5-Turbo<br>Difficulty Estimator]
    end
    subgraph "External Services"
    I[Wolfram Alpha API]
    end
    A -->|User Interaction| B
    B -->|Proxy Requests| C
    C --> D
    C --> E
    C -->|Main Chat| F
    C -->|Math Queries| I
    F -->|Response| C
    I -->|Raw Result| C
    C -->|Extract Result| G
    G -->|Formatted Result| C
    C -->|Estimate Difficulty| H
    H -->|Update Session| D
    classDef frontend fill:#e0f7fa,stroke:#006064;
    classDef api fill:#fff9c4,stroke:#fbc02d;
    classDef backend fill:#e8f5e9,stroke:#2e7d32;
    classDef ai fill:#f3e5f5,stroke:#6a1b9a;
    classDef external fill:#fbe9e7,stroke:#bf360c;
    class A frontend;
    class B api;
    class C,D,E backend;
    class F,G,H ai;
    class I external;
```

MathBuddy uses a Next.js frontend for the user interface and a FastAPI backend to manage AI models and external services.

## Technical Highlights

1. AI Model Integration: Combines GPT-4o and GPT-3.5-Turbo for specialized tasks
2. Real-Time Processing: Uses WebSocket connections for instant interactions
3. Serverless Architecture: Employs cloud functions for scalability
4. State Management: Implements techniques to maintain conversation context
5. API Integration: Works with OpenAI and Wolfram Alpha APIs

## Getting Started

1. Clone the repository:
   ```
   git clone https://github.com/parvanovkp/MathBuddyBot
   cd MathBuddyBot
   ```

2. Install dependencies:
   ```
   npm install
   ```

3. Set up environment variables:
   
   In the root directory, create a `.env` file for backend variables:
   ```
   OPENAI_API_KEY=your_openai_api_key
   WOLFRAM_ALPHA_APP_ID=your_wolfram_alpha_app_id
   API_KEY=your_custom_api_key
   FRONTEND_URL=http://localhost:3000
   ```

   In the `frontend` directory, create a `.env.local` file:
   ```
   NEXT_PUBLIC_API_KEY=your_custom_api_key
   BACKEND_URL=http://localhost:8000
   ```

4. Start the development servers:
   ```
   # In the root directory (backend)
   cd backend
   uvicorn main:app --reload

   # In a new terminal, navigate to the frontend directory
   cd frontend
   npm run dev
   ```

## Contributing

Contributions to MathBuddy are welcome. Please ensure that your code adheres to the existing style and includes appropriate tests. For major changes, open an issue first to discuss your proposed changes.

## License

MathBuddy is open-source software licensed under the MIT License.