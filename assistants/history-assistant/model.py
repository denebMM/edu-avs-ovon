import torch
import torch.nn as nn

class NeuralNet(nn.Module):
    def __init__(self, input_size, hidden_size, num_classes):
        super(NeuralNet, self).__init__()
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.fc2 = nn.Linear(hidden_size, hidden_size)
        self.fc3 = nn.Linear(hidden_size, hidden_size)
        self.fc4 = nn.Linear(hidden_size, hidden_size)  # Add an additional hidden layer
        self.fc5 = nn.Linear(hidden_size, hidden_size)  # Add one more hidden layer
        self.fc6 = nn.Linear(hidden_size, num_classes)   # Adjust the output layer
        self.relu = nn.ReLU()

    def forward(self, x):
        out = self.fc1(x)
        out = self.relu(out)
        out = self.fc2(out)
        out = self.relu(out)
        out = self.fc3(out)
        out = self.relu(out)
        out = self.fc4(out)  # Pass through the additional hidden layer
        out = self.relu(out)  # Apply activation function
        out = self.fc5(out)  # Pass through the second additional hidden layer
        out = self.relu(out)  # Apply activation function
        out = self.fc6(out)  # Adjust for the new output layer
        return out
