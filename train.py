import torch
from multiprocessing import Pool
from AirfoilEnv import *
from tensormanager import TensorManager

class Train:
    def __init__(
        self,
        env,
        env_name,
        agent,
        epochs,
        mini_batch_size,
        epsilon,
        horizon,
    ):
        self.env = env
        self.env_name = env_name
        self.agent = agent
        self.epsilon = epsilon
        self.horizon = horizon
        self.epochs = epochs
        self.n_iterations = 100
        self.mini_batch_size = mini_batch_size
        self.start_time = 0
        self.running_reward = 0
        self.steps_history = []
        self.rewards_history = []
        self.actor_loss_history = []
        self.critic_loss_history = []
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def train(
        self,
        tensor_manager,
    ):
        actor_loss, critic_loss = 0, 0
        returns = tensor_manager.advantages_tensor + tensor_manager.values_tensor[:,:-1]
        for epoch in range(self.epochs):
            for (
                state,
                action,
                return_,
                adv,
                old_value,
                old_log_prob,
            ) in self.choose_mini_batch(
                self.mini_batch_size,
                tensor_manager.states_tensor,
                tensor_manager.actions_tensor,
                returns,
                tensor_manager.advantages_tensor,
                tensor_manager.values_tensor,
                tensor_manager.log_probs_tensor,
            ):
                state, action, return_, adv, old_value, old_log_prob = (
                    state.squeeze(),
                    action.squeeze(),
                    return_.squeeze(),
                    adv.squeeze(),
                    old_value.squeeze(),
                    old_log_prob.squeeze(),
                )
                # 업데이트된 숨겨진 상태를 사용하여 critic 및 actor 업데이트
                value = self.agent.get_value(state, use_grad=True)

                critic_loss = (return_ - value).pow(2).mean()

                new_dist = self.agent.choose_dists(state, use_grad=True)
                new_log_prob = new_dist.log_prob(action).sum(dim=1)
                ratio = (new_log_prob - old_log_prob).exp()

                actor_loss_temp = self.compute_actor_loss(ratio, adv)

                entropy_loss = new_dist.entropy().mean()

                actor_loss_temp += -0.03 * entropy_loss
                actor_loss += actor_loss_temp / self.mini_batch_size
                critic_loss += critic_loss / self.mini_batch_size

                self.agent.optimize(actor_loss_temp, critic_loss)

        return actor_loss, critic_loss

    

    def get_gae(self, tensor_manager, gamma=1, lam=0.95):
        rewards = tensor_manager.rewards_tensor
        values = tensor_manager.values_tensor
        num_env, horizon = rewards.shape
        advs = torch.zeros_like(rewards).to(rewards.device)

        # Adjusting the values after the end of the episodes
        for env_idx in range(num_env):
            gae = 0
            for t in reversed(range(horizon)):
                delta = (
                    rewards[env_idx, t]
                    + gamma * values[env_idx, t + 1]
                    - values[env_idx, t]
                )
                gae = delta + gamma * lam * gae
                advs[env_idx, t] = gae
        return advs

    def compute_actor_loss(self, ratio, adv):
        pg_loss1 = adv * ratio
        pg_loss2 = adv * torch.clamp(ratio, 1 - self.epsilon, 1 + self.epsilon)
        loss = -torch.min(pg_loss1, pg_loss2).mean()

        return loss


    def step(self):
        for iteration in range(1, 1 + self.n_iterations):
            tensor_manager = TensorManager(
                env_num=1,
                horizon=self.horizon,
                state_shape=(2, 200),
                action_dim=2,
                device=self.device,
            )
            states = self.env.reset()
            states = torch.tensor(states, dtype=torch.float32).unsqueeze(0).permute(0,2,1).to(self.device)
            # 1 episode (data collection)
            for t in range(self.horizon):
                # Actor
                dists = self.agent.choose_dists(states, use_grad=False)
                actions = self.agent.choose_actions(dists)
                scaled_actions = self.agent.scale_actions(actions).squeeze()
                log_prob = dists.log_prob(actions).sum(dim=1)

                # Critic
                value = self.agent.get_value(states, use_grad=False)
                next_states, rewards = self.env.step(scaled_actions)

                tensor_manager.update_tensors(
                    states,
                    actions,
                    rewards,
                    value,
                    log_prob,
                    t,
                )
                

                states = torch.tensor(next_states, dtype=torch.float32).unsqueeze(0).permute(0,2,1).to(self.device)
            
            next_value = self.agent.get_value(states, use_grad=False)
            tensor_manager.values_tensor[:, -1] = next_value.squeeze()

            advs = self.get_gae(tensor_manager)
            tensor_manager.advantages_tensor = advs
            # Train the agent
            actor_loss, critic_loss = self.train(tensor_manager)
            eval_rewards = torch.sum(tensor_manager.rewards_tensor)

            self.print_logs(iteration, actor_loss.detach().numpy(), critic_loss.detach().numpy(), eval_rewards, t)

    def choose_mini_batch(
        self,
        mini_batch_size,
        states,
        actions,
        returns,
        advs,
        values,
        log_probs,
    ):

        for _ in range(self.horizon // mini_batch_size):
            # 무작위로 mini_batch_size 개의 인덱스를 선택
            indices = torch.randperm(self.horizon)[:mini_batch_size].to(
                states.device
            )
            yield (
                states[:, indices],
                actions[:, indices],
                returns[:, indices],
                advs[:, indices],
                values[:, indices],
                log_probs[:, indices],
            )

    def print_logs(self, iteration, actor_loss, critic_loss, eval_rewards, steps):

        if iteration == 1:
            self.running_reward = eval_rewards
        else:
            self.running_reward = self.running_reward * 0.99 + eval_rewards * 0.01
        running_reward = torch.mean(self.running_reward)
        current_actor_lr = self.agent.actor_optimizer.param_groups[0]["lr"]
        current_critic_lr = self.agent.critic_optimizer.param_groups[0]["lr"]

        self.steps_history.append(steps)
        self.rewards_history.append(running_reward.item())
        self.actor_loss_history.append(actor_loss)
        self.critic_loss_history.append(critic_loss)

        actor_loss = actor_loss.item() if torch.is_tensor(actor_loss) else actor_loss
        critic_loss = (
            critic_loss.item() if torch.is_tensor(critic_loss) else critic_loss
        )
        # eval_rewards의 평균을 계산
        if torch.is_tensor(eval_rewards):
            eval_rewards_val = eval_rewards.mean().item()
        else:
            eval_rewards_val =  eval_rewards

        running_reward_val =  torch.mean(self.running_reward).item()
        self.plot_and_save()


    def plot_and_save(self):
        fig, axs = plt.subplots(2, 2, figsize=(12, 10))
        axs[0, 0].plot(self.steps_history, label="Average Steps")
        axs[0, 0].set_title("Average Steps")
        axs[0, 1].plot(self.rewards_history, label="Running Reward")
        axs[0, 1].set_title("Running Reward")
        axs[1, 0].plot(self.actor_loss_history, label="Actor Loss")
        axs[1, 0].set_title("Actor Loss")
        axs[1, 1].plot(self.critic_loss_history, label="Critic Loss")
        axs[1, 1].set_title("Critic Loss")

        for ax in axs.flat:
            ax.set(xlabel="Iteration", ylabel="Value")
            ax.label_outer()
            ax.legend(loc="best")

        fig.subplots_adjust(hspace=0.1, wspace=0.1)

        plt.savefig(f"results/results_graphs.png")
        plt.close()