# HistoryBot

Welcome to the HistoryBot repository! HistoryBot is a virtual assistant specializing in historical inquiries. Trained on the intents.json dataset, it is adept at recognizing and responding to a variety of historical questions within its training data's scope. With regular updates, HistoryBot ensures an adaptable and enriching user experience.

**Model Architecture:**

The architecture of the HistoryBot model is designed using PyTorch, a popular deep learning framework. Let's delve into a more detailed explanation of its structure:

1. **Input Layer:**
   - The model takes historical text data as input. Each data point is represented as a feature vector, with dimensions corresponding to the input size.

2. **Linear Layers:**
   - The core of the model consists of three linear layers (`l1`, `l2`, and `l3`). These layers are also known as fully connected or dense layers.
   - The first linear layer (`l1`) takes the input data and transforms it using a linear operation, essentially performing a weighted sum of the input features. The output is then passed through a Rectified Linear Unit (ReLU) activation function, introducing non-linearity to the model.
   - The second linear layer (`l2`) repeats this process, taking the output from the first layer, performing another linear transformation, and applying the ReLU activation.
   - The third linear layer (`l3`) follows the same pattern, providing the final transformation.

3. **ReLU Activation:**
   - The ReLU activation function introduces non-linearity by replacing any negative values in the output with zero. This allows the model to learn complex patterns and relationships in the data.

4. **Regression-Based Approach:**
   - The absence of an activation function like softmax at the end indicates a regression-based approach. In typical classification problems, softmax is used to convert model outputs into probability distributions over classes. However, in this case, the model seems to be directly providing numerical values without converting them into probabilities. This suggests a regression task where the model predicts continuous values.

**Dataset:**

The dataset used for training HistoryBot is available [here](https://drive.google.com/file/d/1vjvs09SlEqdfnEuhPSDY_jVjzWYK6US4/view). It forms the foundation for HistoryBot's historical knowledge and question-answering capabilities.

**Live App:**

Experience HistoryBot in action through the live app accessible [here](https://history-bot-eha8.onrender.com/). Engage in historical conversations and witness the bot's prowess in providing informative and intriguing responses.
