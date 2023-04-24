import time, math, json, torch
import torch.nn as nn
import torch.optim as optim



class Trainer:
    def __init__(self, config, model, train_dataloader, valid_dataloader):
        super(Trainer, self).__init__()
        
        self.model = model
        self.clip = config.clip
        self.device = config.device
        self.strategy = config.strategy
        self.n_epochs = config.n_epochs
        self.vocab_size = config.vocab_size

        self.scaler = torch.cuda.amp.GradScaler()
        self.iters_to_accumulate = config.iters_to_accumulate

        self.early_stop = config.early_stop
        self.patience = config.patience
        
        self.train_dataloader = train_dataloader
        self.valid_dataloader = valid_dataloader

        self.bert_optimizer = optim.AdamW(self.model.parameters(), lr=config.learning_rate * 0.1)
        self.optimizer = optim.AdamW(self.model.parameters(), lr=config.learning_rate)
        self.scheduler = optim.lr_scheduler.ReduceLROnPlateau(self.optimizer, 'min')
        
        self.ckpt_path = config.ckpt_path
        self.record_path = f"ckpt/{self.model_name}.json"
        self.record_keys = ['epoch', 'train_loss', 'train_ppl', 'valid_loss', 
                            'valid_ppl', 'learning_rate', 'train_time']


    def print_epoch(self, record_dict):
        print(f"""Epoch {record_dict['epoch']}/{self.n_epochs} | \
              Time: {record_dict['train_time']}""".replace(' ' * 14, ''))
        
        print(f"""  >> Train Loss: {record_dict['train_loss']:.3f} | \
              Train PPL: {record_dict['train_ppl']:.2f}""".replace(' ' * 14, ''))

        print(f"""  >> Valid Loss: {record_dict['valid_loss']:.3f} | \
              Valid PPL: {record_dict['valid_ppl']:.2f}\n""".replace(' ' * 14, ''))


    @staticmethod
    def measure_time(start_time, end_time):
        elapsed_time = end_time - start_time
        elapsed_min = int(elapsed_time / 60)
        elapsed_sec = int(elapsed_time - (elapsed_min * 60))
        return f"{elapsed_min}m {elapsed_sec}s"


    def train(self):
        best_loss, records = float('inf'), []
        for epoch in range(1, self.n_epochs + 1):
            start_time = time.time()

            record_vals = [epoch, *self.train_epoch(), *self.valid_epoch(), 
                           self.optimizer.param_groups[0]['lr'],
                           self.measure_time(start_time, time.time())]
            record_dict = {k: v for k, v in zip(self.record_keys, record_vals)}
            
            records.append(record_dict)
            self.print_epoch(record_dict)
            
            val_loss = record_dict['valid_loss']
            self.scheduler.step(val_loss)

            #save best model
            if best_loss > val_loss:
                best_loss = val_loss
                torch.save({'epoch': epoch,
                            'model_state_dict': self.model.state_dict(),
                            'optimizer_state_dict': self.optimizer.state_dict()},
                            self.ckpt_path)
            
        #save train_records
        with open(self.record_path, 'w') as fp:
            json.dump(records, fp)



    def train_epoch(self):
        self.model.train()
        epoch_loss = 0
        tot_len = len(self.train_dataloader)

        for idx, batch in enumerate(self.train_dataloader):
            x = batch['input_ids'].to(self.device) 
            x_seg_mask = batch['token_type_ids'].to(self.device)
            y = batch['labels'].to(self.device)

            loss = self.model(x, x_seg_mask, y).loss
            loss.backward()
            nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=self.clip)
            
            self.optimizer.step()
            self.optimizer.zero_grad()

            epoch_loss += loss.item()
        
        epoch_loss = round(epoch_loss / tot_len, 3)
        epoch_ppl = round(math.exp(epoch_loss), 3)    
        return epoch_loss, epoch_ppl
        
    

    def valid_epoch(self):
        self.model.eval()
        epoch_loss = 0
        tot_len = len(self.valid_dataloader)
        
        with torch.no_grad():
            for batch in self.valid_dataloader:                
                x = batch['input_ids'].to(self.device) 
                x_seg_mask = batch['token_type_ids'].to(self.device)
                y = batch['labels'].to(self.device)

                loss = self.model(x, x_seg_mask, y).loss

        
        epoch_loss = round(epoch_loss / tot_len, 3)
        epoch_ppl = round(math.exp(epoch_loss), 3)        
        return epoch_loss, epoch_ppl