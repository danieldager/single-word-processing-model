import sys
import time
import argparse
import pandas as pd
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim

""" PATHS """
FILE_DIR = Path(__file__).resolve()
ROOT_DIR = FILE_DIR.parent.parent.parent
MODELS_DIR = ROOT_DIR / "code" / "models"
WEIGHTS_DIR = ROOT_DIR / "weights"
WEIGHTS_DIR.mkdir(exist_ok=True)
sys.path.append(str(MODELS_DIR))

from Phonemes import Phonemes
from EncoderRNN import EncoderRNN
from DecoderRNN import DecoderRNN

from plots import training_curves
from utils import seed_everything, set_device, Timer

device = set_device()

""" ARGUMENT PARSER """
def parse_args():
    parser = argparse.ArgumentParser()
    
    parser.add_argument('--n_epochs', 
                       type=int, 
                       default=10,
                       help='Number of training epochs')
    
    parser.add_argument('--h_size', 
                       type=int, 
                       default=4,
                       help='Hidden layer size')
    
    parser.add_argument('--n_layers', 
                       type=int, 
                       default=1,
                       help='Number of hidden layers')
    
    parser.add_argument('--dropout', 
                       type=float, 
                       default=0.1,
                       help='Dropout rate (0.0 to 1.0)')
    
    parser.add_argument('--l_rate', 
                       type=float, 
                       default=0.001,
                       help='Learning rate')
    
    args = parser.parse_args() 
    return args

""" TRAINING LOOP """
def train_repetition(P: Phonemes, params: dict) -> pd.DataFrame:

    """ LOAD VARIABLES """
    vocab_size = P.vocab_size
    train_dataloader = P.train_dataloader
    valid_dataloader = P.valid_dataloader

    """ UNPACK PARAMETERS """
    num_epochs     = params['n_epochs']
    hidden_size    = params['h_size']
    num_layers     = params['n_layers']
    dropout        = params['dropout']
    learning_rate  = params['l_rate']

    # Print hyperparameters
    print(f"Training model with hyperparameters:")
    print(f"Epochs:    {num_epochs}")
    print(f"Hidden:    {hidden_size}")
    print(f"Layers:    {num_layers}")
    print(f"Dropout:   {dropout}")
    print(f"Learning:  {learning_rate}")

    """ INITIALIZE MODEL """
    model = f'e{num_epochs}_h{hidden_size}_l{num_layers}_d{dropout}_r{learning_rate}'
    MODEL_WEIGHTS_DIR = WEIGHTS_DIR / model
    MODEL_WEIGHTS_DIR.mkdir(exist_ok=True)
 
    encoder = EncoderRNN(
        input_size=vocab_size, hidden_size=hidden_size,
        num_layers=num_layers, dropout=dropout
    ).to(device)

    decoder = DecoderRNN(
        hidden_size=hidden_size, output_size=vocab_size,
        num_layers=num_layers, dropout=dropout
    ).to(device)

    # # if CUDA, use DataParallel
    # if torch.cuda.device_count() > 1:
    #     encoder = nn.DataParallel(encoder).to(device)
    #     decoder = nn.DataParallel(decoder).to(device)

    criterion = nn.CrossEntropyLoss()
    parameters = list(encoder.parameters()) + list(decoder.parameters())
    optimizer = optim.Adam(parameters, lr=learning_rate)

    """ TRAINING LOOP """
    train_losses = []
    valid_losses = []
    epoch_times = []
    timer = Timer()

    for epoch in range(num_epochs):
        print(f"Epoch {epoch+1}/{num_epochs}")
        epoch_start = time.time()
        encoder.train()
        decoder.train()
        train_loss = 0

        timer.start()
        for i, (inputs, targets) in enumerate(train_dataloader):
            print(f"{i+1}/{len(train_dataloader)}", end='\r')

            inputs = inputs.to(device)
            targets = targets.to(device)
            optimizer.zero_grad()

            # Forward passes
            timer.start()
            encoder_hidden = encoder(inputs)
            timer.stop("Encoder Forward Pass")

            timer.start()
            decoder_input = torch.zeros(1, inputs.shape[1], hidden_size, device=device)
            decoder_output = decoder(decoder_input, encoder_hidden)
            timer.stop("Decoder Forward Pass")

            # Loss computation
            timer.start()
            outputs = decoder_output.view(-1, vocab_size)  
            targets = targets.view(-1)
            loss = criterion(outputs, targets)
            timer.stop("Loss Computation")

            # Backward pass
            timer.start()
            loss.backward()
            optimizer.step()
            timer.stop("Backward Pass")

            train_loss += loss.item()
    
        train_loss /= len(train_dataloader)
        train_losses.append(train_loss)

        """ VALIDATION LOOP """
        timer.start()
        encoder.eval()
        decoder.eval()
        valid_loss = 0

        with torch.no_grad():
            for inputs, targets in valid_dataloader:
                inputs = inputs.to(device)
                targets = targets.to(device)

                encoder_hidden = encoder(inputs)
                decoder_input = torch.zeros(1, inputs.shape[1], hidden_size, device=device)
                decoder_output = decoder(decoder_input, encoder_hidden)

                outputs = decoder_output.view(-1, vocab_size)
                targets = targets.view(-1)
                loss = criterion(outputs, targets)
                valid_loss += loss.item()

        valid_loss /= len(valid_dataloader)
        valid_losses.append(valid_loss)
        timer.stop("Validation")

        epoch_time = time.time() - epoch_start
        epoch_times.append(epoch_time)
        log = f"Epoch {epoch+1}: Train: {train_loss:.3f} "
        log += f"Valid: {valid_loss:.3f} Time: {epoch_time:.2f}s"
        print(log)

        """ CHECKPOINTS """
        # Save model weights for every epoch
        encoder_path = MODEL_WEIGHTS_DIR / f"encoder{epoch+1}.pth"
        decoder_path = MODEL_WEIGHTS_DIR / f"decoder{epoch+1}.pth"
        torch.save(encoder.state_dict(), encoder_path)
        torch.save(decoder.state_dict(), decoder_path)

    """ PLOT LOSS """
    training_curves(train_losses, valid_losses, model, num_epochs)

    # Print timing summary
    timer.summary()

    return model

if __name__ == "__main__":
    seed_everything()
    P = Phonemes()
    args = parse_args()
    parameters = vars(args)
    train_repetition(P, parameters)
